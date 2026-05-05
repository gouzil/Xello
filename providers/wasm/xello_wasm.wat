(module
  (memory (export "memory") 1)
  (data (i32.const 0) "wasm\00")
  (data (i32.const 16) "hello world from wasm implementation, called by wasm-host\00")
  (func (export "xello_language") (result i32)
    i32.const 0)
  (func (export "xello_hello") (param i32) (result i32)
    i32.const 16))
