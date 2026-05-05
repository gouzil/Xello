use libloading::{Library, Symbol};
use pyo3::prelude::*;
use pyo3::types::{PyList, PyModule};
use std::env;
use std::ffi::{CStr, CString};
use std::fs;
use std::os::raw::c_char;
use std::process::{self, Command};
use std::time::Instant;

type HelloFn = unsafe extern "C" fn(*const c_char) -> *const c_char;

#[derive(Clone, Copy, PartialEq, Eq)]
enum RustPythonBridge {
    Pyo3,
    Capi,
}

#[derive(Clone)]
struct CallResult {
    caller: String,
    callee: String,
    bridge: String,
    duration_ns: u128,
    message: String,
    output: String,
}

fn shared_ext() -> &'static str {
    if cfg!(target_os = "macos") {
        ".dylib"
    } else {
        ".so"
    }
}

fn bridge_kind(callee: &str, python_bridge: RustPythonBridge) -> Option<&'static str> {
    match callee {
        "python" if python_bridge == RustPythonBridge::Pyo3 => Some("PyO3 embedded Python"),
        "python" => Some("Python shared library via Python/C API"),
        "c" => Some("libloading crate"),
        "go" => Some("libloading crate over C ABI fallback"),
        "rust" => Some("direct Rust function"),
        "cpp" => Some("C++ shared library via C ABI"),
        "zig" => Some("Zig shared library via C ABI"),
        "kotlin_native" => Some("Kotlin/Native dynamic library via C ABI"),
        "wasm" => Some("WebAssembly C ABI shim"),
        _ => None,
    }
}

fn rust_hello(caller: &str) -> String {
    format!("hello world from rust implementation, called by {}", caller)
}

fn call_python_via_pyo3() -> Result<(String, u128), String> {
    Python::attach(|py| -> PyResult<(String, u128)> {
        let sys = PyModule::import(py, "sys")?;
        let path = sys.getattr("path")?.cast_into::<PyList>()?;
        path.insert(0, ".")?;
        let module = PyModule::import(py, "runners.python.xello_python_impl")?;
        let hello = module.getattr("hello")?;
        let start = Instant::now();
        let message: String = hello.call1(("rust",))?.extract()?;
        Ok((message, start.elapsed().as_nanos().max(1)))
    })
    .map_err(|err| err.to_string())
}

fn call_provider(callee: &str) -> Result<(String, u128), String> {
    let path = format!("build/lib/libxello_{}{}", callee, shared_ext());
    let library = unsafe { Library::new(path) }.map_err(|err| err.to_string())?;
    let hello: Symbol<HelloFn> =
        unsafe { library.get(b"xello_hello") }.map_err(|err| err.to_string())?;
    let caller = CString::new("rust").unwrap();
    let start = Instant::now();
    let message_ptr = unsafe { hello(caller.as_ptr()) };
    let message = unsafe { CStr::from_ptr(message_ptr) }
        .to_string_lossy()
        .into_owned();
    let duration_ns = start.elapsed().as_nanos().max(1);
    Ok((message, duration_ns))
}

fn call_edge(callee: &str, python_bridge: RustPythonBridge) -> Result<CallResult, String> {
    let bridge = bridge_kind(callee, python_bridge)
        .ok_or_else(|| format!("unknown language: {}", callee))?
        .to_string();

    let (message, duration_ns) = match callee {
        "python" if python_bridge == RustPythonBridge::Pyo3 => call_python_via_pyo3()?,
        "python" => call_provider(callee)?,
        "rust" => {
            let start = Instant::now();
            (rust_hello("rust"), start.elapsed().as_nanos().max(1))
        }
        "c" | "go" | "cpp" | "zig" | "kotlin_native" | "wasm" => call_provider(callee)?,
        _ => unreachable!(),
    };

    let output = format!(
        "rust runner -> {} implementation via {}: {}",
        callee, bridge, message
    );
    Ok(CallResult {
        caller: "rust".to_string(),
        callee: callee.to_string(),
        bridge,
        duration_ns,
        message,
        output,
    })
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
            ch if ch.is_control() => escaped.push_str(&format!("\\u{:04x}", ch as u32)),
            ch => escaped.push(ch),
        }
    }
    escaped.push('"');
    escaped
}

fn print_results(results: &[CallResult], json_output: bool) {
    if json_output {
        println!("[");
        for (index, item) in results.iter().enumerate() {
            let comma = if index + 1 == results.len() { "" } else { "," };
            println!(
                "  {{\"caller\":{},\"callee\":{},\"bridge\":{},\"duration_ns\":{},\"message\":{},\"output\":{}}}{}",
                json_string(&item.caller),
                json_string(&item.callee),
                json_string(&item.bridge),
                item.duration_ns,
                json_string(&item.message),
                json_string(&item.output),
                comma
            );
        }
        println!("]");
        return;
    }

    for item in results {
        println!("{} (duration_ns={})", item.output, item.duration_ns);
    }
}

fn parse_edges(raw: &str) -> Result<Vec<(String, String)>, String> {
    let mut edges = Vec::new();
    for item in raw.split(',') {
        let edge = item.trim();
        if edge.is_empty() {
            continue;
        }
        let parts: Vec<_> = edge.split(':').collect();
        if parts.len() != 2 {
            return Err(format!(
                "invalid chain edge {:?}; expected caller:callee",
                edge
            ));
        }
        let caller = parts[0].trim().to_lowercase();
        let callee = parts[1].trim().to_lowercase();
        if bridge_kind(&caller, RustPythonBridge::Pyo3).is_none() {
            return Err(format!("unknown language: {}", caller));
        }
        if bridge_kind(&callee, RustPythonBridge::Pyo3).is_none() {
            return Err(format!("unknown language: {}", callee));
        }
        edges.push((caller, callee));
    }
    if edges.is_empty() {
        return Err("chain requires at least one caller:callee edge".to_string());
    }
    Ok(edges)
}

fn language_list() -> Vec<&'static str> {
    let known_languages = [
        "python",
        "c",
        "go",
        "rust",
        "cpp",
        "zig",
        "kotlin_native",
        "wasm",
    ];
    let Ok(manifest) = fs::read_to_string("build/xello_languages.json") else {
        return vec!["python", "c", "go", "rust", "cpp"];
    };
    let Some(key) = manifest.find("\"languages\"") else {
        return vec!["python", "c", "go", "rust", "cpp"];
    };
    let Some(start_offset) = manifest[key..].find('[') else {
        return vec!["python", "c", "go", "rust", "cpp"];
    };
    let start = key + start_offset;
    let Some(end_offset) = manifest[start..].find(']') else {
        return vec!["python", "c", "go", "rust", "cpp"];
    };
    let raw_languages = &manifest[start..start + end_offset];
    known_languages
        .into_iter()
        .filter(|language| raw_languages.contains(&format!("\"{}\"", language)))
        .collect()
}

fn runner_command(language: &str, args: &[&str]) -> Result<Command, String> {
    let mut command = match language {
        "python" => {
            let mut cmd = Command::new("python3");
            cmd.args(["tools/run_from.py", "python"]);
            cmd
        }
        "c" => Command::new("build/bin/xello_c"),
        "go" => Command::new("build/bin/xello_go"),
        "rust" => Command::new("build/bin/xello_rust"),
        "cpp" => Command::new("build/bin/xello_cpp"),
        "zig" => Command::new("build/bin/xello_zig"),
        "kotlin_native" => Command::new("build/bin/xello_kotlin_native.kexe"),
        "wasm" => {
            let mut cmd = Command::new("python3");
            cmd.arg("runners/wasm/xello_wasm.py");
            cmd
        }
        _ => return Err(format!("unknown language: {}", language)),
    };
    command.args(args);
    Ok(command)
}

fn call_via_runner(caller: &str, callee: &str) -> Result<String, String> {
    if caller == "rust" {
        let item = call_edge(callee, RustPythonBridge::Pyo3)?;
        let mut buffer = Vec::new();
        write_json_results(&[item], &mut buffer)?;
        return String::from_utf8(buffer).map_err(|err| err.to_string());
    }

    let output = runner_command(caller, &["--json", "call", callee])?
        .output()
        .map_err(|err| err.to_string())?;
    if output.status.success() {
        String::from_utf8(output.stdout).map_err(|err| err.to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).into_owned())
    }
}

fn json_item_to_line(json: &str) -> Result<String, String> {
    let trimmed = json.trim();
    if !trimmed.starts_with('[') || !trimmed.ends_with(']') {
        return Err("runner returned non-array JSON".to_string());
    }
    Ok(trimmed[1..trimmed.len() - 1]
        .trim()
        .trim_end_matches(',')
        .to_string())
}

fn run_chain_json(raw: &str) -> Result<String, String> {
    let edges = parse_edges(raw)?;
    let mut items = Vec::with_capacity(edges.len());
    for (caller, callee) in edges {
        items.push(json_item_to_line(&call_via_runner(&caller, &callee)?)?);
    }
    Ok(format!("[\n  {}\n]", items.join(",\n  ")))
}

fn run_matrix_json() -> Result<String, String> {
    let mut items = Vec::new();
    let languages = language_list();
    for caller in &languages {
        for callee in &languages {
            items.push(json_item_to_line(&call_via_runner(caller, callee)?)?);
        }
    }
    Ok(format!("[\n  {}\n]", items.join(",\n  ")))
}

fn run_fanout_json(caller: &str) -> Result<String, String> {
    if bridge_kind(caller, RustPythonBridge::Pyo3).is_none() {
        return Err(format!("unknown language: {}", caller));
    }
    let mut items = Vec::new();
    let languages = language_list();
    for callee in languages {
        items.push(json_item_to_line(&call_via_runner(caller, callee)?)?);
    }
    Ok(format!("[\n  {}\n]", items.join(",\n  ")))
}

fn run_chain_human(raw: &str) -> Result<(), String> {
    for (caller, callee) in parse_edges(raw)? {
        if caller == "rust" {
            print_results(&[call_edge(&callee, RustPythonBridge::Pyo3)?], false);
            continue;
        }
        let status = runner_command(&caller, &["call", &callee])?
            .status()
            .map_err(|err| err.to_string())?;
        if !status.success() {
            return Err(format!(
                "{} runner failed for {}:{}",
                caller, caller, callee
            ));
        }
    }
    Ok(())
}

fn run_matrix_human() -> Result<(), String> {
    let languages = language_list();
    for caller in &languages {
        for callee in &languages {
            if *caller == "rust" {
                print_results(&[call_edge(callee, RustPythonBridge::Pyo3)?], false);
                continue;
            }
            let status = runner_command(caller, &["call", callee])?
                .status()
                .map_err(|err| err.to_string())?;
            if !status.success() {
                return Err(format!(
                    "{} runner failed for {}:{}",
                    caller, caller, callee
                ));
            }
        }
    }
    Ok(())
}

fn run_fanout_human(caller: &str) -> Result<(), String> {
    if bridge_kind(caller, RustPythonBridge::Pyo3).is_none() {
        return Err(format!("unknown language: {}", caller));
    }
    let languages = language_list();
    for callee in languages {
        if caller == "rust" {
            print_results(&[call_edge(callee, RustPythonBridge::Pyo3)?], false);
            continue;
        }
        let status = runner_command(caller, &["call", callee])?
            .status()
            .map_err(|err| err.to_string())?;
        if !status.success() {
            return Err(format!(
                "{} runner failed for {}:{}",
                caller, caller, callee
            ));
        }
    }
    Ok(())
}

fn write_json_results(results: &[CallResult], output: &mut Vec<u8>) -> Result<(), String> {
    use std::io::Write;
    writeln!(output, "[").map_err(|err| err.to_string())?;
    for (index, item) in results.iter().enumerate() {
        let comma = if index + 1 == results.len() { "" } else { "," };
        writeln!(
            output,
            "  {{\"caller\":{},\"callee\":{},\"bridge\":{},\"duration_ns\":{},\"message\":{},\"output\":{}}}{}",
            json_string(&item.caller),
            json_string(&item.callee),
            json_string(&item.bridge),
            item.duration_ns,
            json_string(&item.message),
            json_string(&item.output),
            comma
        )
        .map_err(|err| err.to_string())?;
    }
    writeln!(output, "]").map_err(|err| err.to_string())
}

fn print_json(json: String) -> Result<(), String> {
    println!("{}", json);
    Ok(())
}

fn parse_rust_python_bridge(raw: &str) -> Result<RustPythonBridge, String> {
    match raw {
        "pyo3" => Ok(RustPythonBridge::Pyo3),
        "capi" => Ok(RustPythonBridge::Capi),
        _ => Err(format!("unknown rust->python bridge: {}", raw)),
    }
}

fn parse_call_args(args: &[String]) -> Result<(&str, RustPythonBridge), String> {
    let mut callee: Option<&str> = None;
    let mut python_bridge = RustPythonBridge::Pyo3;
    let mut index = 1;
    while index < args.len() {
        match args[index].as_str() {
            "--bridge" => {
                index += 1;
                if index >= args.len() {
                    return Err(
                        "usage: xello_rust [--json] call [--bridge pyo3|capi] <callee>".to_string(),
                    );
                }
                python_bridge = parse_rust_python_bridge(&args[index])?;
            }
            value if value.starts_with("--") => {
                return Err(format!("unsupported call option: {}", value));
            }
            value => {
                if callee.is_some() {
                    return Err(
                        "usage: xello_rust [--json] call [--bridge pyo3|capi] <callee>".to_string(),
                    );
                }
                callee = Some(value);
            }
        }
        index += 1;
    }
    let callee = callee.ok_or_else(|| {
        "usage: xello_rust [--json] call [--bridge pyo3|capi] <callee>".to_string()
    })?;
    Ok((callee, python_bridge))
}

fn main() {
    let mut args: Vec<String> = env::args().skip(1).collect();
    let json_output = if args.first().map(|value| value.as_str()) == Some("--json") {
        args.remove(0);
        true
    } else {
        false
    };

    if args.is_empty() {
        eprintln!("usage: xello_rust [--json] <call|chain|matrix> ...");
        process::exit(2);
    }

    let result = match args[0].as_str() {
        "call" => parse_call_args(&args).and_then(|(callee, python_bridge)| {
            call_edge(callee, python_bridge).map(|item| print_results(&[item], json_output))
        }),
        "matrix" if args.len() == 1 && json_output => run_matrix_json().and_then(print_json),
        "matrix" if args.len() == 1 => run_matrix_human(),
        "fanout" if args.len() == 2 && json_output => {
            run_fanout_json(&args[1]).and_then(print_json)
        }
        "fanout" if args.len() == 2 => run_fanout_human(&args[1]),
        "chain" if args.len() == 3 && args[1] == "--edges" && json_output => {
            run_chain_json(&args[2]).and_then(print_json)
        }
        "chain" if args.len() == 3 && args[1] == "--edges" => run_chain_human(&args[2]),
        "fanout" => Err("usage: xello_rust [--json] fanout <caller>".to_string()),
        "chain" => Err("usage: xello_rust [--json] chain --edges <caller:callee,...>".to_string()),
        other => Err(format!("unsupported command: {}", other)),
    };

    if let Err(err) = result {
        eprintln!("{}", err);
        process::exit(1);
    }
}
