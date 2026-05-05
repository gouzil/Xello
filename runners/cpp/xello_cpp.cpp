#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <array>
#include <fstream>
#include <string>
#include <vector>

using XelloHelloFn = const char *(*)(const char *);

static uint64_t now_ns() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<uint64_t>(ts.tv_sec) * 1000000000ULL + static_cast<uint64_t>(ts.tv_nsec);
}

static uint64_t positive_duration(uint64_t duration_ns) {
    return duration_ns == 0 ? 1 : duration_ns;
}

static uint64_t elapsed_ns_since(uint64_t start_ns) {
    uint64_t end_ns = now_ns();
    return end_ns <= start_ns ? 1 : end_ns - start_ns;
}

static const char *shared_ext() {
#ifdef __APPLE__
    return ".dylib";
#else
    return ".so";
#endif
}

static std::string provider_path(const char *language) {
    return std::string("build/lib/libxello_") + language + shared_ext();
}

static const char *bridge_kind(const char *callee) {
    if (strcmp(callee, "python") == 0) {
        return "Python shared library via Python/C API";
    }
    if (strcmp(callee, "c") == 0) {
        return "C shared library via C ABI";
    }
    if (strcmp(callee, "go") == 0) {
        return "Go shared library via C ABI";
    }
    if (strcmp(callee, "rust") == 0) {
        return "Rust shared library via C ABI";
    }
    if (strcmp(callee, "cpp") == 0) {
        return "direct C++ function";
    }
    if (strcmp(callee, "zig") == 0) {
        return "Zig shared library via C ABI";
    }
    if (strcmp(callee, "kotlin_native") == 0) {
        return "Kotlin/Native dynamic library via C ABI";
    }
    if (strcmp(callee, "wasm") == 0) {
        return "WebAssembly C ABI shim";
    }
    return nullptr;
}

static const char *cpp_hello(const char *caller) {
    static std::string message;
    message = "hello world from cpp implementation, called by ";
    message += caller == nullptr ? "unknown" : caller;
    return message.c_str();
}

static int call_provider(const char *callee, std::string &message, uint64_t &duration_ns) {
    std::string path = provider_path(callee);
    void *handle = dlopen(path.c_str(), RTLD_NOW);
    if (handle == nullptr) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return 1;
    }

    auto hello = reinterpret_cast<XelloHelloFn>(dlsym(handle, "xello_hello"));
    if (hello == nullptr) {
        fprintf(stderr, "provider is missing xello_hello\n");
        dlclose(handle);
        return 1;
    }

    uint64_t start = now_ns();
    const char *raw = hello("cpp");
    message = raw == nullptr ? "" : raw;
    duration_ns = elapsed_ns_since(start);
    dlclose(handle);
    return 0;
}

static int call_edge(const char *callee, bool json_output) {
    const char *bridge = bridge_kind(callee);
    if (bridge == nullptr) {
        fprintf(stderr, "unknown language: %s\n", callee);
        return 2;
    }

    std::string message;
    uint64_t duration_ns = 0;
    int rc = 0;
    if (strcmp(callee, "cpp") == 0) {
        uint64_t start = now_ns();
        message = cpp_hello("cpp");
        duration_ns = elapsed_ns_since(start);
    } else {
        rc = call_provider(callee, message, duration_ns);
    }
    if (rc != 0) {
        return rc;
    }

    if (json_output) {
        printf("[{\"caller\":\"cpp\",\"callee\":\"%s\",\"bridge\":\"%s\",\"duration_ns\":%llu,"
               "\"message\":\"%s\",\"output\":\"cpp runner -> %s implementation via %s: %s\"}]\n",
               callee, bridge, static_cast<unsigned long long>(duration_ns), message.c_str(), callee, bridge,
               message.c_str());
    } else {
        printf("cpp runner -> %s implementation via %s: %s (duration_ns=%llu)\n", callee, bridge, message.c_str(),
               static_cast<unsigned long long>(duration_ns));
    }
    return 0;
}

static bool is_language(const char *language) {
    return bridge_kind(language) != nullptr;
}

static std::vector<const char *> load_languages() {
    std::array<const char *, 8> known_languages = {"python", "c", "go", "rust", "cpp", "zig", "kotlin_native", "wasm"};
    std::ifstream manifest("build/xello_languages.json");
    if (!manifest) {
        return {"python", "c", "go", "rust", "cpp"};
    }

    std::string content((std::istreambuf_iterator<char>(manifest)), std::istreambuf_iterator<char>());
    size_t key = content.find("\"languages\"");
    size_t start = key == std::string::npos ? std::string::npos : content.find('[', key);
    size_t end = start == std::string::npos ? std::string::npos : content.find(']', start);
    if (start == std::string::npos || end == std::string::npos) {
        return {"python", "c", "go", "rust", "cpp"};
    }

    std::string raw_languages = content.substr(start, end - start);
    std::vector<const char *> languages;
    for (const char *language : known_languages) {
        std::string token = std::string("\"") + language + "\"";
        if (raw_languages.find(token) != std::string::npos) {
            languages.push_back(language);
        }
    }
    return languages;
}

static void edge_command(const char *caller, const char *callee, bool json_output, char *buffer, size_t size) {
    const char *json_flag = json_output ? "--json " : "";
    if (strcmp(caller, "python") == 0) {
        snprintf(buffer, size, "python3 tools/run_from.py python %scall %s", json_flag, callee);
    } else if (strcmp(caller, "c") == 0) {
        snprintf(buffer, size, "build/bin/xello_c %scall %s", json_flag, callee);
    } else if (strcmp(caller, "go") == 0) {
        snprintf(buffer, size, "build/bin/xello_go %scall %s", json_flag, callee);
    } else if (strcmp(caller, "rust") == 0) {
        snprintf(buffer, size, "build/bin/xello_rust %scall %s", json_flag, callee);
    } else if (strcmp(caller, "kotlin_native") == 0) {
        snprintf(buffer, size, "build/bin/xello_kotlin_native.kexe %scall %s", json_flag, callee);
    } else if (strcmp(caller, "wasm") == 0) {
        snprintf(buffer, size, "python3 runners/wasm/xello_wasm.py %scall %s", json_flag, callee);
    } else if (strcmp(caller, "zig") == 0) {
        snprintf(buffer, size, "build/bin/xello_zig %scall %s", json_flag, callee);
    } else {
        snprintf(buffer, size, "build/bin/xello_cpp %scall %s", json_flag, callee);
    }
}

static int run_edge_command_json(const char *caller, const char *callee, bool *first) {
    char command[512];
    edge_command(caller, callee, true, command, sizeof(command));

    FILE *pipe = popen(command, "r");
    if (pipe == nullptr) {
        fprintf(stderr, "failed to run: %s\n", command);
        return 1;
    }

    char output[4096];
    size_t used = fread(output, 1, sizeof(output) - 1, pipe);
    output[used] = '\0';
    int rc = pclose(pipe);
    if (rc != 0) {
        fprintf(stderr, "runner command failed: %s\n", command);
        return 1;
    }

    char *start = strchr(output, '[');
    char *end = strrchr(output, ']');
    if (start == nullptr || end == nullptr || end <= start) {
        fprintf(stderr, "runner returned invalid json: %s\n", output);
        return 1;
    }
    start++;
    while (*start == ' ' || *start == '\n' || *start == '\t') {
        start++;
    }
    while (end > start && (end[-1] == ' ' || end[-1] == '\n' || end[-1] == '\t')) {
        end--;
    }
    *end = '\0';

    if (!*first) {
        printf(",\n");
    }
    printf("  %s", start);
    *first = false;
    return 0;
}

static int run_edge_command_human(const char *caller, const char *callee) {
    char command[512];
    edge_command(caller, callee, false, command, sizeof(command));
    int rc = system(command);
    if (rc != 0) {
        fprintf(stderr, "runner command failed: %s\n", command);
        return 1;
    }
    return 0;
}

static int run_edge(const char *caller, const char *callee, bool json_output, bool *first_json) {
    if (!is_language(caller)) {
        fprintf(stderr, "unknown language: %s\n", caller);
        return 2;
    }
    if (!is_language(callee)) {
        fprintf(stderr, "unknown language: %s\n", callee);
        return 2;
    }
    if (json_output) {
        return run_edge_command_json(caller, callee, first_json);
    }
    return run_edge_command_human(caller, callee);
}

static int run_matrix(bool json_output) {
    std::vector<const char *> languages = load_languages();
    bool first = true;
    if (json_output) {
        printf("[\n");
    }
    for (const char *caller : languages) {
        for (const char *callee : languages) {
            int rc = run_edge(caller, callee, json_output, &first);
            if (rc != 0) {
                return rc;
            }
        }
    }
    if (json_output) {
        printf("\n]\n");
    }
    return 0;
}

static int run_fanout(const char *caller, bool json_output) {
    std::vector<const char *> languages = load_languages();
    bool first_json = true;
    if (!is_language(caller)) {
        fprintf(stderr, "unknown language: %s\n", caller);
        return 2;
    }
    if (json_output) {
        printf("[\n");
    }
    for (const char *callee : languages) {
        int rc = run_edge(caller, callee, json_output, &first_json);
        if (rc != 0) {
            return rc;
        }
    }
    if (json_output) {
        printf("\n]\n");
    }
    return 0;
}

static int run_chain(const char *raw_edges, bool json_output) {
    char edges[2048];
    snprintf(edges, sizeof(edges), "%s", raw_edges);
    bool first_json = true;
    bool seen_edge = false;
    if (json_output) {
        printf("[\n");
    }

    char *cursor = edges;
    char *edge = nullptr;
    while ((edge = strsep(&cursor, ",")) != nullptr) {
        if (*edge == '\0') {
            continue;
        }
        char *separator = strchr(edge, ':');
        if (separator == nullptr) {
            fprintf(stderr, "invalid chain edge %s; expected caller:callee\n", edge);
            return 2;
        }
        *separator = '\0';
        const char *caller = edge;
        const char *callee = separator + 1;
        int rc = run_edge(caller, callee, json_output, &first_json);
        if (rc != 0) {
            return rc;
        }
        seen_edge = true;
    }

    if (!seen_edge) {
        fprintf(stderr, "chain requires at least one caller:callee edge\n");
        return 2;
    }
    if (json_output) {
        printf("\n]\n");
    }
    return 0;
}

int main(int argc, char **argv) {
    bool json_output = false;
    int argi = 1;
    if (argc > 1 && strcmp(argv[1], "--json") == 0) {
        json_output = true;
        argi = 2;
    }

    if (argi >= argc) {
        fprintf(stderr, "usage: xello_cpp [--json] <call|chain|matrix> ...\n");
        return 2;
    }

    const char *command = argv[argi++];
    if (strcmp(command, "call") == 0) {
        if (argi >= argc) {
            fprintf(stderr, "usage: xello_cpp [--json] call <callee>\n");
            return 2;
        }
        return call_edge(argv[argi], json_output);
    }
    if (strcmp(command, "matrix") == 0) {
        return run_matrix(json_output);
    }
    if (strcmp(command, "fanout") == 0) {
        if (argi >= argc) {
            fprintf(stderr, "usage: xello_cpp [--json] fanout <caller>\n");
            return 2;
        }
        return run_fanout(argv[argi], json_output);
    }
    if (strcmp(command, "chain") == 0) {
        if (argi + 1 >= argc || strcmp(argv[argi], "--edges") != 0) {
            fprintf(stderr, "usage: xello_cpp [--json] chain --edges <caller:callee,...>\n");
            return 2;
        }
        return run_chain(argv[argi + 1], json_output);
    }

    fprintf(stderr, "unsupported command: %s\n", command);
    return 2;
}
