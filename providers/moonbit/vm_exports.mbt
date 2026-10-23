///|
#export_name("xello_bytes_make")
pub fn bytes_make(length : Int32) -> FixedArray[Byte] {
  FixedArray::make(length, 0)
}

///|
#export_name("xello_bytes_freeze")
pub fn bytes_freeze(bytes : FixedArray[Byte]) -> Bytes {
  Bytes::from_array(bytes[:])
}

///|
#export_name("xello_bytes_length")
#borrow(bytes)
pub fn bytes_length(bytes : Bytes) -> Int32 {
  bytes.length()
}

///|
#export_name("xello_bytes_get")
#borrow(bytes)
pub fn bytes_get(bytes : Bytes, index : Int32) -> Int32 {
  bytes[index].to_int()
}

///|
#export_name("xello_bytes_set")
#borrow(bytes)
pub fn bytes_set(
  bytes : FixedArray[Byte],
  index : Int32,
  value : Int32,
) -> Unit {
  bytes[index] = value.to_byte()
}

///|
#export_name("xello_bytes_release")
pub fn bytes_release(bytes : Bytes) -> Unit {
  ignore(bytes)
}
