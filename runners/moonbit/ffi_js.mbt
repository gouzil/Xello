///|
extern "js" fn read_manifest() -> Bytes =
  #| () => globalThis.xello.read_manifest()

///|
extern "js" fn now_ns() -> Int64 =
  #| () => globalThis.xello.now_ns()

///|
extern "js" fn call_provider(
  caller : Bytes,
  callee : Bytes,
  duration : FixedArray[Int64],
) -> Bytes =
  #| (caller, callee, duration) => globalThis.xello.call_provider(caller, callee, duration)

///|
extern "js" fn fail(message : Bytes, status : Int32) -> Unit =
  #| (message, status) => globalThis.xello.fail(message, status)
