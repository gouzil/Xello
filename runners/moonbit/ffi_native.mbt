///|
extern "C" fn read_manifest() -> Bytes = "xello_moonbit_read_manifest"

///|
extern "C" fn now_ns() -> Int64 = "xello_moonbit_now_ns"

///|
#borrow(caller, callee, duration)
extern "C" fn call_provider(
  caller : Bytes,
  callee : Bytes,
  duration : FixedArray[Int64],
) -> Bytes = "xello_moonbit_call_provider"

///|
#borrow(message)
extern "C" fn fail(message : Bytes, status : Int32) -> Unit = "xello_moonbit_fail"
