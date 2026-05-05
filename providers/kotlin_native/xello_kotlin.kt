import kotlinx.cinterop.ByteVar
import kotlinx.cinterop.CPointer
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.allocArray
import kotlinx.cinterop.nativeHeap
import kotlinx.cinterop.set
import kotlinx.cinterop.toKString

@OptIn(ExperimentalForeignApi::class)
private val language = nativeHeap.allocArray<ByteVar>(14)

@OptIn(ExperimentalForeignApi::class)
private val message = nativeHeap.allocArray<ByteVar>(256)

@OptIn(ExperimentalForeignApi::class)
private fun writeCString(buffer: CPointer<ByteVar>, value: String, size: Int): CPointer<ByteVar> {
    val bytes = value.encodeToByteArray()
    val limit = minOf(bytes.size, size - 1)
    for (index in 0 until limit) {
        buffer[index] = bytes[index]
    }
    buffer[limit] = 0.toByte()
    return buffer
}

@OptIn(ExperimentalForeignApi::class)
fun xelloLanguage(): CPointer<ByteVar> = writeCString(language, "kotlin_native", 14)

@OptIn(ExperimentalForeignApi::class)
fun xelloHello(caller: CPointer<ByteVar>?): CPointer<ByteVar> {
    val safeCaller = caller?.toKString() ?: "unknown"
    return writeCString(message, "hello world from kotlin_native implementation, called by $safeCaller", 256)
}
