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

///|
suberror CliError {
  CliError(String)
}

///|
struct Manifest {
  languages : Array[String]
} derive(@json.FromJson)

///|
struct CallResult {
  caller : String
  callee : String
  bridge : String
  duration_ns : Int64
  message : String
  step : Int32
}

///|
fn language_name(language : String) -> String raise CliError {
  match language {
    "python" => "Python"
    "c" => "C"
    "go" => "Go"
    "rust" => "Rust"
    "cpp" => "C++"
    "zig" => "Zig"
    "kotlin_native" => "Kotlin/Native"
    "wasm" => "WebAssembly"
    "moonbit" => "MoonBit"
    _ => raise CliError("unknown language: \{language}")
  }
}

///|
fn validate_language(
  language : String,
  languages : Array[String],
) -> Unit raise CliError {
  if !languages.contains(language) {
    raise CliError("unknown language: \{language}")
  }
}

///|
fn run_edge(
  caller : String,
  callee : String,
  step : Int32,
) -> CallResult raise CliError {
  let name = language_name(callee)
  let duration : FixedArray[Int64] = [0L]
  let (bridge, message) = if caller == "moonbit" && callee == "moonbit" {
    let start = now_ns()
    let message = @provider.hello(caller)
    duration[0] = now_ns() - start
    ("direct MoonBit function", message)
  } else {
    let message = @utf8.decode_lossy(
      call_provider(
        @utf8.encode(caller + "\u0000"),
        @utf8.encode(callee + "\u0000"),
        duration,
      ),
    )
    let bridge = if callee == "wasm" {
      "WebAssembly C ABI shim"
    } else if caller == "moonbit" {
      if callee == "python" {
        "Python shared library via Python/C API"
      } else {
        "\{name} shared library via C ABI"
      }
    } else if callee == "python" {
      "Python provider function via Python/C API"
    } else {
      "\{name} provider function via C ABI"
    }
    (bridge, message)
  }
  { caller, callee, bridge, duration_ns: duration[0].max(1L), message, step, }
}

///|
fn print_results(results : Array[CallResult], json_output : Bool) -> Unit {
  let json_results : Array[Json] = []
  for item in results {
    let output = "\{item.caller} runner -> \{item.callee} implementation via \{item.bridge}: \{item.message}"
    if json_output {
      let fields : Map[String, Json] = {
        "caller": Json(item.caller),
        "callee": Json(item.callee),
        "bridge": Json(item.bridge),
        // Int64 defaults to a JSON string; retain the exact integer token instead.
        "duration_ns": Json::number(
          item.duration_ns.to_double(),
          repr=item.duration_ns.to_string(),
        ),
        "message": Json(item.message),
        "output": Json(output),
      }
      if item.step > 0 {
        fields["step"] = Json(item.step)
      }
      json_results.push(Json::object(fields))
    } else {
      let prefix = if item.step > 0 { "step=\{item.step} " } else { "" }
      println("\{prefix}\{output} (duration_ns=\{item.duration_ns})")
    }
  }
  if json_output {
    println(Json::array(json_results).stringify())
  }
}

///|
fn run(args : Array[String]) -> Unit raise {
  let json_output = args.length() > 0 && args[0] == "--json"
  let args = if json_output { args[1:].to_owned() } else { args }
  guard args.length() > 0 else {
    raise CliError(
      "usage: xello_moonbit [--json] <call|fanout|chain|matrix> ...",
    )
  }
  let manifest : Manifest = @json.from_json(
    @json.parse(@utf8.decode_lossy(read_manifest())),
  )
  let languages = manifest.languages
  for language in languages {
    ignore(language_name(language))
  }
  let edges : Array[(String, String)] = []
  let is_chain = args[0] == "chain"
  match args[0] {
    "call" => {
      guard args.length() == 2 else {
        raise CliError("usage: xello_moonbit [--json] call <callee>")
      }
      edges.push(("moonbit", args[1]))
    }
    "fanout" => {
      guard args.length() == 2 else {
        raise CliError("usage: xello_moonbit [--json] fanout <caller>")
      }
      validate_language(args[1], languages)
      for callee in languages {
        edges.push((args[1], callee))
      }
    }
    "matrix" => {
      guard args.length() == 1 else {
        raise CliError("usage: xello_moonbit [--json] matrix")
      }
      for caller in languages {
        for callee in languages {
          edges.push((caller, callee))
        }
      }
    }
    "chain" => {
      guard args.length() == 3 && args[1] == "--edges" else {
        raise CliError(
          "usage: xello_moonbit [--json] chain --edges <caller:callee,...>",
        )
      }
      for raw in args[2].split(",") {
        let edge = raw.trim().to_owned()
        if edge.is_empty() {
          continue
        }
        let parts = edge.split(":").to_array()
        guard parts.length() == 2 else {
          raise CliError("invalid chain edge \{edge}; expected caller:callee")
        }
        edges.push(
          (
            parts[0].trim().to_owned().to_lower(),
            parts[1].trim().to_owned().to_lower(),
          ),
        )
      }
      guard !edges.is_empty() else {
        raise CliError("chain requires at least one caller:callee edge")
      }
    }
    _ => raise CliError("unsupported command: \{args[0]}")
  }
  for (caller, callee) in edges {
    validate_language(caller, languages)
    validate_language(callee, languages)
  }
  let results : Array[CallResult] = []
  for index, (caller, callee) in edges {
    results.push(run_edge(caller, callee, if is_chain { index + 1 } else { 0 }))
  }
  print_results(results, json_output)
}

///|
fn main {
  run(@env.args()[1:].to_owned()) catch {
    CliError(message) => fail(@utf8.encode(message), 2)
    error => fail(@utf8.encode(error.to_string()), 2)
  }
}
