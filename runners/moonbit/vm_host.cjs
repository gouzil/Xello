const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "../..");
const bridge = require(path.join(root, "build/lib/xello_moonbit_node.node"));
const backend = process.argv[2];
const args = process.argv.slice(3);
const isJs = backend === "js";
const decode = (value) =>
  Buffer.from(value).toString("utf8").replace(/\0.*$/s, "");
const host = {
  read_manifest() {
    return new Uint8Array(fs.readFileSync("build/xello_languages.json"));
  },
  now_ns() {
    return process.hrtime.bigint();
  },
  call_provider(caller, callee, duration) {
    const [message, elapsed] = bridge.call(decode(caller), decode(callee));
    duration[0] = elapsed;
    return new Uint8Array(message);
  },
  fail(message, status) {
    process.stderr.write(decode(message) + "\n");
    process.exit(status);
  },
};

try {
  if (isJs) {
    globalThis.xello = host;
    process.argv = ["xello_moonbit", ...args];
    require(path.join(root, "build/lib/xello_moonbit_runner_js.cjs"));
  } else {
    let text = "";
    let input;
    let output;
    let message;
    const imports = {
      wasi_snapshot_preview1: {
        fd_write(fd, vectors, count, written) {
          if (fd !== 1 && fd !== 2) return 8;
          const memory = api.memory.buffer;
          const view = new DataView(memory);
          let total = 0;
          for (let i = 0; i < count; i++) {
            const offset = view.getUint32(vectors + i * 8, true);
            const length = view.getUint32(vectors + i * 8 + 4, true);
            total += fs.writeSync(fd, new Uint8Array(memory, offset, length));
          }
          view.setUint32(written, total, true);
          return 0;
        },
      },
      xello: {
        now_ns: host.now_ns,
        read(kind) {
          input =
            kind === 0
              ? fs.readFileSync("build/xello_languages.json")
              : message;
          return input.length;
        },
        read_byte: (index) => input[index],
        write: (length) => {
          output = Buffer.alloc(length);
        },
        write_byte: (index, value) => {
          output[index] = value;
        },
        call() {
          const [caller, callee] = output.toString("utf8").split("\0");
          const result = bridge.call(caller, callee);
          message = result[0];
          return result[1];
        },
        fail(status) {
          process.stderr.write(output.toString("utf8") + "\n");
          process.exit(status);
        },
      },
      spectest: {
        print_char(value) {
          if (value === 10) {
            console.log(text);
            text = "";
          } else text += String.fromCharCode(value);
        },
      },
      __moonbit_fs_unstable: {
        args_get: () => ["xello_moonbit", ...args],
        begin_read_string_array: (array) => ({ array, index: 0 }),
        string_array_read_string: (handle) =>
          handle.array[handle.index++] ?? "ffi_end_of_/string_array",
        finish_read_string_array: () => {},
        begin_read_string: (value) => ({ value, index: 0 }),
        string_read_char(handle) {
          if (handle.index >= handle.value.length) return -1;
          const value = handle.value.codePointAt(handle.index);
          handle.index += value > 0xffff ? 2 : 1;
          return value;
        },
        finish_read_string: () => {},
      },
    };
    const module = new WebAssembly.Module(
      fs.readFileSync(
        path.join(root, `build/lib/xello_moonbit_runner_${backend}.wasm`),
      ),
    );
    const api = new WebAssembly.Instance(module, imports).exports;
    api._start();
  }
} catch (error) {
  process.stderr.write(error.message + "\n");
  process.exitCode = 1;
}
