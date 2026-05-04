use std::env;
use std::ffi::{CStr, CString};
use std::fmt::Write;
use std::os::raw::{c_char, c_int, c_void};
use std::process;
use std::time::Instant;

type HelloFn = unsafe extern "C" fn(*const c_char) -> *const c_char;
type LanguageFn = unsafe extern "C" fn() -> *const c_char;

#[cfg(target_os = "macos")]
#[link(name = "dl")]
unsafe extern "C" {}

unsafe extern "C" {
    fn dlopen(filename: *const c_char, flag: c_int) -> *mut c_void;
    fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
    fn dlclose(handle: *mut c_void) -> c_int;
    fn dlerror() -> *const c_char;
}

const RTLD_NOW: c_int = 2;

fn last_dl_error() -> String {
    unsafe {
        let err = dlerror();
        if err.is_null() {
            "unknown dlerror".to_string()
        } else {
            CStr::from_ptr(err).to_string_lossy().into_owned()
        }
    }
}

fn json_string(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len() + 2);
    escaped.push('"');
    for ch in value.chars() {
        match ch {
            '"' => escaped.push_str("\\\""),
            '\\' => escaped.push_str("\\\\"),
            '\n' => escaped.push_str("\\n"),
            '\r' => escaped.push_str("\\r"),
            '\t' => escaped.push_str("\\t"),
            ch if ch.is_control() => {
                write!(&mut escaped, "\\u{:04x}", ch as u32).expect("writing to string cannot fail");
            }
            ch => escaped.push(ch),
        }
    }
    escaped.push('"');
    escaped
}

fn main() {
    let mut args = env::args().skip(1);
    let first = args.next();
    let (json_output, path) = match (first.as_deref(), args.next()) {
        (Some("--json"), Some(path)) => (true, path),
        (Some(path), None) => (false, path.to_string()),
        _ => {
            eprintln!("usage: xello_rust_host [--json] <provider-library>");
            process::exit(2);
        }
    };

    if args.next().is_some() {
        eprintln!("usage: xello_rust_host [--json] <provider-library>");
        process::exit(2);
    }

    let c_path = CString::new(path).expect("provider path must not contain nul bytes");
    let handle = unsafe { dlopen(c_path.as_ptr(), RTLD_NOW) };
    if handle.is_null() {
        eprintln!("dlopen failed: {}", last_dl_error());
        process::exit(1);
    }

    let hello_name = CString::new("xello_hello").unwrap();
    let language_name = CString::new("xello_language").unwrap();

    let hello_symbol = unsafe { dlsym(handle, hello_name.as_ptr()) };
    let language_symbol = unsafe { dlsym(handle, language_name.as_ptr()) };
    if hello_symbol.is_null() || language_symbol.is_null() {
        eprintln!("provider is missing required xello symbols");
        unsafe {
            dlclose(handle);
        }
        process::exit(1);
    }

    let hello: HelloFn = unsafe { std::mem::transmute(hello_symbol) };
    let language: LanguageFn = unsafe { std::mem::transmute(language_symbol) };
    let caller = CString::new("rust").unwrap();

    let provider = unsafe { CStr::from_ptr(language()) }.to_string_lossy();
    let start = Instant::now();
    let message_ptr = unsafe { hello(caller.as_ptr()) };
    let duration_ns = start.elapsed().as_nanos().max(1);
    let message = unsafe { CStr::from_ptr(message_ptr) }.to_string_lossy();
    let output = format!("rust host -> {} provider: {}", provider, message);

    if json_output {
        println!(
            "{{\"caller\":\"rust\",\"callee\":{},\"duration_ns\":{},\"output\":{}}}",
            json_string(&provider),
            duration_ns,
            json_string(&output)
        );
    } else {
        println!("{} (duration_ns={})", output, duration_ns);
    }

    unsafe {
        dlclose(handle);
    }
}
