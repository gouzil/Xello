import kotlinx.cinterop.ByteVar
import kotlinx.cinterop.CPointer
import kotlinx.cinterop.CFunction
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.alloc
import kotlinx.cinterop.allocArray
import kotlinx.cinterop.cstr
import kotlinx.cinterop.invoke
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr
import kotlinx.cinterop.reinterpret
import kotlinx.cinterop.toKString
import platform.posix.RTLD_NOW
import platform.posix.dlclose
import platform.posix.dlopen
import platform.posix.dlsym
import platform.posix.fclose
import platform.posix.fgets
import platform.posix.fopen
import platform.posix.fprintf
import platform.posix.stderr
import kotlin.system.exitProcess

private val languages = listOf("python", "c", "go", "rust", "cpp", "zig", "kotlin_native", "wasm")

private data class CallResult(
    val caller: String,
    val callee: String,
    val bridge: String,
    val durationNs: Long,
    val message: String,
    val step: Int = 0,
)

private fun nowMark(): kotlin.time.TimeMark = kotlin.time.TimeSource.Monotonic.markNow()

private fun elapsedNsSince(start: kotlin.time.TimeMark): Long =
    start.elapsedNow().inWholeNanoseconds.let { if (it <= 0) 1 else it }

@OptIn(ExperimentalForeignApi::class)
private fun sharedExt(): String = if (platform.posix.uname(memScoped { alloc<platform.posix.utsname>().ptr }) == 0) {
    if (platform.posix.getenv("XELLO_FORCE_SO") == null && platform.posix.getenv("OSTYPE")?.toKString()?.contains("darwin") == true) ".dylib" else ".so"
} else {
    ".so"
}

private fun bridgeKind(callee: String): String? = when (callee) {
    "python" -> "Python shared library via Python/C API"
    "c" -> "C shared library via C ABI"
    "go" -> "Go shared library via C ABI"
    "rust" -> "Rust shared library via C ABI"
    "cpp" -> "C++ shared library via C ABI"
    "zig" -> "Zig shared library via C ABI"
    "kotlin_native" -> "direct Kotlin/Native function"
    "wasm" -> "WebAssembly C ABI shim"
    else -> null
}

private fun providerBridgeKind(callee: String): String? = when (callee) {
    "python" -> "Python provider function via Python/C API"
    "c" -> "C provider function via C ABI"
    "go" -> "Go provider function via C ABI"
    "rust" -> "Rust provider function via C ABI"
    "cpp" -> "C++ provider function via C ABI"
    "zig" -> "Zig provider function via C ABI"
    "kotlin_native" -> "Kotlin/Native provider function via C ABI"
    "wasm" -> "WebAssembly C ABI shim"
    else -> null
}

private fun kotlinHello(caller: String): String = "hello world from kotlin_native implementation, called by $caller"

@OptIn(ExperimentalForeignApi::class)
private fun callProvider(callee: String): Pair<String, Long> = callProviderAs("kotlin_native", callee)

@OptIn(ExperimentalForeignApi::class)
private fun callProviderAs(callerName: String, callee: String): Pair<String, Long> = memScoped {
    val handle = dlopen("build/lib/libxello_${callee}${sharedExt()}", RTLD_NOW)
        ?: error("dlopen failed")
    try {
        val symbol = dlsym(handle, "xello_hello")
            ?: error("provider is missing xello_hello")
        val hello = symbol.reinterpret<CFunction<(CPointer<ByteVar>?) -> CPointer<ByteVar>?>>()
        val caller = callerName.cstr.ptr
        val start = nowMark()
        val message = hello(caller)?.toKString() ?: ""
        message to elapsedNsSince(start)
    } finally {
        dlclose(handle)
    }
}

private fun callEdge(callee: String): CallResult {
    if (callee !in languages) error("unknown language: $callee")
    val bridge = bridgeKind(callee) ?: error("unknown language: $callee")
    val (message, durationNs) = when (callee) {
        "kotlin_native" -> {
            val start = nowMark()
            kotlinHello("kotlin_native") to elapsedNsSince(start)
        }
        else -> callProvider(callee)
    }
    return CallResult("kotlin_native", callee, bridge, durationNs, message)
}

private fun callEdgeAs(caller: String, callee: String): CallResult {
    if (caller == "kotlin_native") return callEdge(callee)
    if (caller !in languages) error("unknown language: $caller")
    if (callee !in languages) error("unknown language: $callee")
    if (caller == "wasm" && callee == "wasm") {
        val start = nowMark()
        return CallResult(caller, callee, "WebAssembly runtime host", elapsedNsSince(start), "hello world from wasm implementation, called by wasm")
    }
    val bridge = providerBridgeKind(callee) ?: error("unknown language: $callee")
    val (message, durationNs) = callProviderAs(caller, callee)
    return CallResult(caller, callee, bridge, durationNs, message)
}

private fun jsonString(value: String): String = buildString {
    append('"')
    for (ch in value) {
        when (ch) {
            '"' -> append("\\\"")
            '\\' -> append("\\\\")
            '\n' -> append("\\n")
            '\r' -> append("\\r")
            '\t' -> append("\\t")
            else -> append(ch)
        }
    }
    append('"')
}

private fun printResults(results: List<CallResult>, jsonOutput: Boolean) {
    if (jsonOutput) {
        println("[")
        results.forEachIndexed { index, item ->
            val comma = if (index + 1 == results.size) "" else ","
            val output = "${item.caller} runner -> ${item.callee} implementation via ${item.bridge}: ${item.message}"
            val stepPrefix = if (item.step > 0) "\"step\":${item.step}," else ""
            println(
                "  {$stepPrefix\"caller\":${jsonString(item.caller)},\"callee\":${jsonString(item.callee)},\"bridge\":${jsonString(item.bridge)},\"duration_ns\":${item.durationNs},\"message\":${jsonString(item.message)},\"output\":${jsonString(output)}}$comma"
            )
        }
        println("]")
        return
    }
    results.forEach { item ->
        val stepPrefix = if (item.step > 0) "step=${item.step} " else ""
        println("${stepPrefix}${item.caller} runner -> ${item.callee} implementation via ${item.bridge}: ${item.message} (duration_ns=${item.durationNs})")
    }
}

@OptIn(ExperimentalForeignApi::class)
private fun loadLanguages(): List<String> = memScoped {
    val file = fopen("build/xello_languages.json", "r") ?: return@memScoped listOf("python", "c", "go", "rust", "cpp")
    val buffer = allocArray<ByteVar>(8192)
    val builder = StringBuilder()
    try {
        while (fgets(buffer, 8192, file) != null) {
            builder.append(buffer.toKString())
        }
    } finally {
        fclose(file)
    }
    val content = builder.toString()
    languages.filter { content.contains("\"$it\"") }
}

private fun parseEdges(raw: String): List<Pair<String, String>> {
    val edges = raw.split(",").mapNotNull { item ->
        val edge = item.trim()
        if (edge.isEmpty()) {
            null
        } else {
            val parts = edge.split(":")
            if (parts.size != 2) error("invalid chain edge $edge; expected caller:callee")
            val caller = parts[0].trim().lowercase()
            val callee = parts[1].trim().lowercase()
            if (caller !in languages) error("unknown language: $caller")
            if (callee !in languages) error("unknown language: $callee")
            caller to callee
        }
    }
    if (edges.isEmpty()) error("chain requires at least one caller:callee edge")
    return edges
}

private fun runMatrix(): List<CallResult> {
    val currentLanguages = loadLanguages()
    return currentLanguages.flatMap { caller -> currentLanguages.map { callee -> callEdgeAs(caller, callee) } }
}

private fun runFanout(caller: String): List<CallResult> {
    if (caller !in languages) error("unknown language: $caller")
    return loadLanguages().map { callee -> callEdgeAs(caller, callee) }
}

private fun runChain(rawEdges: String): List<CallResult> =
    parseEdges(rawEdges).mapIndexed { index, edge ->
        val result = callEdgeAs(edge.first, edge.second)
        result.copy(step = index + 1)
    }

@OptIn(ExperimentalForeignApi::class)
fun main(rawArgs: Array<String>) {
    var args = rawArgs.toList()
    val jsonOutput = args.firstOrNull() == "--json"
    if (jsonOutput) args = args.drop(1)
    if (args.isEmpty()) {
        fprintf(stderr, "usage: xello_kotlin_native [--json] <call|chain|matrix|fanout> ...\n")
        exitProcess(2)
    }
    try {
        when (args[0]) {
            "call" -> {
                if (args.size != 2) {
                    fprintf(stderr, "usage: xello_kotlin_native [--json] call <callee>\n")
                    exitProcess(2)
                }
                printResults(listOf(callEdge(args[1])), jsonOutput)
            }
            "matrix" -> printResults(runMatrix(), jsonOutput)
            "fanout" -> {
                if (args.size != 2) {
                    fprintf(stderr, "usage: xello_kotlin_native [--json] fanout <caller>\n")
                    exitProcess(2)
                }
                printResults(runFanout(args[1]), jsonOutput)
            }
            "chain" -> {
                if (args.size != 3 || args[1] != "--edges") {
                    fprintf(stderr, "usage: xello_kotlin_native [--json] chain --edges <caller:callee,...>\n")
                    exitProcess(2)
                }
                printResults(runChain(args[2]), jsonOutput)
            }
            else -> {
                fprintf(stderr, "unsupported command: ${args[0]}\n")
                exitProcess(2)
            }
        }
    } catch (exc: Throwable) {
        fprintf(stderr, "${exc.message}\n")
        exitProcess(1)
    }
}
