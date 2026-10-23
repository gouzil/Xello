///|
#export_name("xello_moonbit_hello")
pub fn hello_bytes(caller : Bytes) -> Bytes {
  @utf8.encode(hello(@utf8.decode_lossy(caller)) + "\u0000")
}
