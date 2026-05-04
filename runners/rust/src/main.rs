use libloading::{Library, Symbol};
use std::env;
use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::process::{self, Command};
use std::time::Instant;

type HelloFn = unsafe extern "C" fn(*const c_char) -> *const c_char;

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

fn bridge_kind(callee: &str) -> Option<&'static str> {
    match callee {
        "python" => Some("std::process Python runner"),
        "c" => Some("libloading crate"),
        "go" => Some("libloading crate over C ABI fallback"),
        "rust" => Some("direct Rust function"),
        _ => None,
    }
}

fn rust_hello(caller: &str) -> String {
    format!("hello world from rust implementation, called by {}", caller)
}

fn call_python() -> Result<(String, u128), String> {
    let start = Instant::now();
    let output = Command::new("python3")
        .args(["runners/python/xello_python.py", "--json", "call", "python"])
        .output()
        .map_err(|err| err.to_string())?;
    let duration_ns = start.elapsed().as_nanos().max(1);
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).into_owned());
    }
    let text = String::from_utf8_lossy(&output.stdout);
    if !text.contains("hello world from python implementation") {
        return Err("python runner returned unexpected output".to_string());
    }
    Ok((
        "hello world from python implementation, called by rust".to_string(),
        duration_ns,
    ))
}

fn call_provider(callee: &str) -> Result<(String, u128), String> {
    let path = format!("build/lib/libxello_{}{}", callee, shared_ext());
    let library = unsafe { Library::new(path) }.map_err(|err| err.to_string())?;
    let hello: Symbol<HelloFn> = unsafe { library.get(b"xello_hello") }.map_err(|err| err.to_string())?;
    let caller = CString::new("rust").unwrap();
    let start = Instant::now();
    let message_ptr = unsafe { hello(caller.as_ptr()) };
    let duration_ns = start.elapsed().as_nanos().max(1);
    let message = unsafe { CStr::from_ptr(message_ptr) }
        .to_string_lossy()
        .into_owned();
    Ok((message, duration_ns))
}

fn call_edge(callee: &str) -> Result<CallResult, String> {
    let bridge = bridge_kind(callee)
        .ok_or_else(|| format!("unknown language: {}", callee))?
        .to_string();

    let (message, duration_ns) = match callee {
        "python" => call_python()?,
        "rust" => {
            let start = Instant::now();
            (rust_hello("rust"), start.elapsed().as_nanos().max(1))
        }
        "c" | "go" => call_provider(callee)?,
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
            return Err(format!("invalid chain edge {:?}; expected caller:callee", edge));
        }
        let caller = parts[0].trim().to_lowercase();
        let callee = parts[1].trim().to_lowercase();
        if bridge_kind(&caller).is_none() {
            return Err(format!("unknown language: {}", caller));
        }
        if bridge_kind(&callee).is_none() {
            return Err(format!("unknown language: {}", callee));
        }
        edges.push((caller, callee));
    }
    if edges.is_empty() {
        return Err("chain requires at least one caller:callee edge".to_string());
    }
    Ok(edges)
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
        _ => return Err(format!("unknown language: {}", language)),
    };
    command.args(args);
    Ok(command)
}

fn call_via_runner(caller: &str, callee: &str) -> Result<String, String> {
    if caller == "rust" {
        let item = call_edge(callee)?;
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
    Ok(trimmed[1..trimmed.len() - 1].trim().trim_end_matches(',').to_string())
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
    for caller in ["python", "c", "go", "rust"] {
        for callee in ["python", "c", "go", "rust"] {
            items.push(json_item_to_line(&call_via_runner(caller, callee)?)?);
        }
    }
    Ok(format!("[\n  {}\n]", items.join(",\n  ")))
}

fn run_fanout_json(caller: &str) -> Result<String, String> {
    if bridge_kind(caller).is_none() {
        return Err(format!("unknown language: {}", caller));
    }
    let mut items = Vec::new();
    for callee in ["python", "c", "go", "rust"] {
        items.push(json_item_to_line(&call_via_runner(caller, callee)?)?);
    }
    Ok(format!("[\n  {}\n]", items.join(",\n  ")))
}

fn run_chain_human(raw: &str) -> Result<(), String> {
    for (caller, callee) in parse_edges(raw)? {
        if caller == "rust" {
            print_results(&[call_edge(&callee)?], false);
            continue;
        }
        let status = runner_command(&caller, &["call", &callee])?
            .status()
            .map_err(|err| err.to_string())?;
        if !status.success() {
            return Err(format!("{} runner failed for {}:{}", caller, caller, callee));
        }
    }
    Ok(())
}

fn run_matrix_human() -> Result<(), String> {
    for caller in ["python", "c", "go", "rust"] {
        for callee in ["python", "c", "go", "rust"] {
            if caller == "rust" {
                print_results(&[call_edge(callee)?], false);
                continue;
            }
            let status = runner_command(caller, &["call", callee])?
                .status()
                .map_err(|err| err.to_string())?;
            if !status.success() {
                return Err(format!("{} runner failed for {}:{}", caller, caller, callee));
            }
        }
    }
    Ok(())
}

fn run_fanout_human(caller: &str) -> Result<(), String> {
    if bridge_kind(caller).is_none() {
        return Err(format!("unknown language: {}", caller));
    }
    for callee in ["python", "c", "go", "rust"] {
        if caller == "rust" {
            print_results(&[call_edge(callee)?], false);
            continue;
        }
        let status = runner_command(caller, &["call", callee])?
            .status()
            .map_err(|err| err.to_string())?;
        if !status.success() {
            return Err(format!("{} runner failed for {}:{}", caller, caller, callee));
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
        "call" if args.len() == 2 => call_edge(&args[1]).map(|item| print_results(&[item], json_output)),
        "matrix" if args.len() == 1 && json_output => run_matrix_json().and_then(print_json),
        "matrix" if args.len() == 1 => run_matrix_human(),
        "fanout" if args.len() == 2 && json_output => run_fanout_json(&args[1]).and_then(print_json),
        "fanout" if args.len() == 2 => run_fanout_human(&args[1]),
        "chain" if args.len() == 3 && args[1] == "--edges" && json_output => {
            run_chain_json(&args[2]).and_then(print_json)
        }
        "chain" if args.len() == 3 && args[1] == "--edges" => run_chain_human(&args[2]),
        "call" => Err("usage: xello_rust [--json] call <callee>".to_string()),
        "fanout" => Err("usage: xello_rust [--json] fanout <caller>".to_string()),
        "chain" => Err("usage: xello_rust [--json] chain --edges <caller:callee,...>".to_string()),
        other => Err(format!("unsupported command: {}", other)),
    };

    if let Err(err) = result {
        eprintln!("{}", err);
        process::exit(1);
    }
}
