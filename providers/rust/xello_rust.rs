use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::ptr;
use std::sync::Mutex;

static LAST_MESSAGE: Mutex<Option<CString>> = Mutex::new(None);
static LANGUAGE: &[u8] = b"rust\0";

#[no_mangle]
pub extern "C" fn xello_language() -> *const c_char {
    LANGUAGE.as_ptr() as *const c_char
}

#[no_mangle]
pub extern "C" fn xello_hello(caller: *const c_char) -> *const c_char {
    let caller_name = if caller.is_null() {
        "unknown".to_string()
    } else {
        unsafe { CStr::from_ptr(caller) }
            .to_string_lossy()
            .into_owned()
    };

    let message = CString::new(format!(
        "hello world from rust implementation, called by {}",
        caller_name
    ))
    .expect("static message does not contain interior nul bytes");

    let mut slot = LAST_MESSAGE.lock().expect("message mutex poisoned");
    *slot = Some(message);
    slot.as_ref().map_or(ptr::null(), |value| value.as_ptr())
}
