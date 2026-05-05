import kotlinx.cinterop.ByteVar
import kotlinx.cinterop.CPointer
import kotlinx.cinterop.CFunction
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.alloc
import kotlinx.cinterop.cstr
import kotlinx.cinterop.invoke
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr
import kotlinx.cinterop.reinterpret
import kotlinx.cinterop.staticCFunction
import kotlinx.cinterop.toKString
import platform.posix.RTLD_NOW
import platform.posix.dlclose
import platform.posix.dlopen
import platform.posix.dlsym
import platform.posix.fprintf
import platform.posix.stderr
import platform.posix.system
import kotlin.system.exitProcess

private val languages = listOf("python", "c", "go", "rust", "cpp", "zig", "kotlin_native", "wasm")

private data class CallResult(
    val caller: String,
    val callee: String,
    val bridge: String,
    val durationNs: Long,
    val message: String,
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

private fun kotlinHello(caller: String): String = "hello world from kotlin_native implementation, called by $caller"

@OptIn(ExperimentalForeignApi::class)
private fun callProvider(callee: String): Pair<String, Long> = memScoped {
    val handle = dlopen("build/lib/libxello_${callee}${sharedExt()}", RTLD_NOW)
        ?: error("dlopen failed")
    try {
        val symbol = dlsym(handle, "xello_hello")
            ?: error("provider is missing xello_hello")
        val hello = symbol.reinterpret<CFunction<(CPointer<ByteVar>?) -> CPointer<ByteVar>?>>()
        val caller = "kotlin_native".cstr.ptr
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
            val output = "kotlin_native runner -> ${item.callee} implementation via ${item.bridge}: ${item.message}"
            println(
                "  {\"caller\":${jsonString(item.caller)},\"callee\":${jsonString(item.callee)},\"bridge\":${jsonString(item.bridge)},\"duration_ns\":${item.durationNs},\"message\":${jsonString(item.message)},\"output\":${jsonString(output)}}$comma"
            )
        }
        println("]")
        return
    }
    results.forEach { item ->
        println("kotlin_native runner -> ${item.callee} implementation via ${item.bridge}: ${item.message} (duration_ns=${item.durationNs})")
    }
}

private fun delegateToPython(jsonOutput: Boolean, args: List<String>) {
    val jsonFlag = if (jsonOutput) "--json " else ""
    val command = "python3 tools/xello.py $jsonFlag${args.joinToString(" ")}"
    val rc = system(command)
    if (rc != 0) exitProcess(1)
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
    if (args[0] == "call") {
        if (args.size != 2) {
            fprintf(stderr, "usage: xello_kotlin_native [--json] call <callee>\n")
            exitProcess(2)
        }
        printResults(listOf(callEdge(args[1])), jsonOutput)
        return
    }
    delegateToPython(jsonOutput, args)
}
