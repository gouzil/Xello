///|
fn host_read(kind : Int32) -> Int32 = "xello" "read"

///|
fn host_read_byte(index : Int32) -> Int32 = "xello" "read_byte"

///|
fn host_write(length : Int32) -> Unit = "xello" "write"

///|
fn host_write_byte(index : Int32, value : Int32) -> Unit = "xello" "write_byte"

///|
fn host_call() -> Int64 = "xello" "call"

///|
fn host_fail(status : Int32) -> Unit = "xello" "fail"

///|
fn now_ns() -> Int64 = "xello" "now_ns"

///|
fn read_buffer(kind : Int32) -> Bytes {
  let length = host_read(kind)
  Bytes::makei(length, fn(index) { host_read_byte(index).to_byte() })
}

///|
fn write_buffer(bytes : Bytes) -> Unit {
  host_write(bytes.length())
  for index in 0..<bytes.length() {
    host_write_byte(index, bytes[index].to_int())
  }
}

///|
fn read_manifest() -> Bytes {
  read_buffer(0)
}

///|
fn call_provider(
  caller : Bytes,
  callee : Bytes,
  duration : FixedArray[Int64],
) -> Bytes {
  host_write(caller.length() + callee.length())
  for index in 0..<caller.length() {
    host_write_byte(index, caller[index].to_int())
  }
  for index in 0..<callee.length() {
    host_write_byte(caller.length() + index, callee[index].to_int())
  }
  duration[0] = host_call()
  read_buffer(1)
}

///|
fn fail(message : Bytes, status : Int32) -> Unit {
  write_buffer(message)
  host_fail(status)
}
