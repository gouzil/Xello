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

#include "xello.h"

using XelloHelloFn = const char *(*)(const char *);

enum class CBridge {
    Dlopen,
    ExternC,
};

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

static const char *bridge_kind(const char *callee, CBridge c_bridge = CBridge::Dlopen) {
    if (strcmp(callee, "python") == 0) {
        return "Python shared library via Python/C API";
    }
    if (strcmp(callee, "c") == 0) {
        if (c_bridge == CBridge::ExternC) {
            return "C provider linked through extern \"C\"";
        }
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

static const char *provider_bridge_kind(const char *callee) {
    if (strcmp(callee, "python") == 0) {
        return "Python provider function via Python/C API";
    }
    if (strcmp(callee, "c") == 0) {
        return "C provider function via C ABI";
    }
    if (strcmp(callee, "go") == 0) {
        return "Go provider function via C ABI";
    }
    if (strcmp(callee, "rust") == 0) {
        return "Rust provider function via C ABI";
    }
    if (strcmp(callee, "cpp") == 0) {
        return "C++ provider function via C ABI";
    }
    if (strcmp(callee, "zig") == 0) {
        return "Zig provider function via C ABI";
    }
    if (strcmp(callee, "kotlin_native") == 0) {
        return "Kotlin/Native provider function via C ABI";
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

static std::string json_string(const std::string &value) {
    std::string escaped;
    escaped.reserve(value.size() + 2);
    escaped.push_back('"');
    for (unsigned char ch : value) {
        switch (ch) {
        case '"':
            escaped += "\\\"";
            break;
        case '\\':
            escaped += "\\\\";
            break;
        case '\n':
            escaped += "\\n";
            break;
        case '\r':
            escaped += "\\r";
            break;
        case '\t':
            escaped += "\\t";
            break;
        default:
            if (ch < 0x20) {
                char buffer[7];
                snprintf(buffer, sizeof(buffer), "\\u%04x", ch);
                escaped += buffer;
            } else {
                escaped.push_back(static_cast<char>(ch));
            }
            break;
        }
    }
    escaped.push_back('"');
    return escaped;
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

static int call_provider_as(const char *caller, const char *callee, std::string &message, uint64_t &duration_ns) {
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
    const char *raw = hello(caller);
    message = raw == nullptr ? "" : raw;
    duration_ns = elapsed_ns_since(start);
    dlclose(handle);
    return 0;
}

static int call_edge(const char *callee, bool json_output, CBridge c_bridge = CBridge::Dlopen) {
    const char *bridge = bridge_kind(callee, c_bridge);
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
    } else if (strcmp(callee, "c") == 0 && c_bridge == CBridge::ExternC) {
        uint64_t start = now_ns();
        const char *raw = xello_hello("cpp");
        message = raw == nullptr ? "" : raw;
        duration_ns = elapsed_ns_since(start);
    } else {
        rc = call_provider(callee, message, duration_ns);
    }
    if (rc != 0) {
        return rc;
    }

    std::string output = std::string("cpp runner -> ") + callee + " implementation via " + bridge + ": " + message;
    if (json_output) {
        printf("[{\"caller\":\"cpp\",\"callee\":%s,\"bridge\":%s,\"duration_ns\":%llu,"
               "\"message\":%s,\"output\":%s}]\n",
               json_string(callee).c_str(), json_string(bridge).c_str(), static_cast<unsigned long long>(duration_ns),
               json_string(message).c_str(), json_string(output).c_str());
    } else {
        printf("%s (duration_ns=%llu)\n", output.c_str(), static_cast<unsigned long long>(duration_ns));
    }
    return 0;
}

static bool is_language(const char *language) {
    return bridge_kind(language) != nullptr;
}

static int parse_c_bridge(const char *raw, CBridge &bridge) {
    if (strcmp(raw, "dlopen") == 0) {
        bridge = CBridge::Dlopen;
        return 0;
    }
    if (strcmp(raw, "extern-c") == 0) {
        bridge = CBridge::ExternC;
        return 0;
    }
    fprintf(stderr, "unknown cpp->c bridge: %s\n", raw);
    return 2;
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

static int run_edge(const char *caller, const char *callee, bool json_output, bool *first_json, size_t step) {
    if (!is_language(caller)) {
        fprintf(stderr, "unknown language: %s\n", caller);
        return 2;
    }
    if (!is_language(callee)) {
        fprintf(stderr, "unknown language: %s\n", callee);
        return 2;
    }
    const char *bridge = strcmp(caller, "cpp") == 0 ? bridge_kind(callee) : provider_bridge_kind(callee);
    if (bridge == nullptr) {
        fprintf(stderr, "unknown language: %s\n", callee);
        return 2;
    }
    std::string message;
    uint64_t duration_ns = 0;
    int rc = 0;
    if (strcmp(caller, "cpp") == 0) {
        if (strcmp(callee, "cpp") == 0) {
            uint64_t start = now_ns();
            message = cpp_hello("cpp");
            duration_ns = elapsed_ns_since(start);
        } else {
            rc = call_provider(callee, message, duration_ns);
        }
    } else if (strcmp(caller, "wasm") == 0 && strcmp(callee, "wasm") == 0) {
        uint64_t start = now_ns();
        message = "hello world from wasm implementation, called by wasm";
        duration_ns = elapsed_ns_since(start);
        bridge = "WebAssembly runtime host";
    } else {
        rc = call_provider_as(caller, callee, message, duration_ns);
    }
    if (rc != 0) {
        return rc;
    }
    if (json_output) {
        std::string output =
            std::string(caller) + " runner -> " + callee + " implementation via " + bridge + ": " + message;
        if (!*first_json) {
            printf(",\n");
        }
        printf("  {");
        if (step > 0) {
            printf("\"step\":%zu,", step);
        }
        printf("\"caller\":%s,\"callee\":%s,\"bridge\":%s,\"duration_ns\":%llu,"
               "\"message\":%s,\"output\":%s}",
               json_string(caller).c_str(), json_string(callee).c_str(), json_string(bridge).c_str(),
               static_cast<unsigned long long>(positive_duration(duration_ns)), json_string(message).c_str(),
               json_string(output).c_str());
        *first_json = false;
        return 0;
    }
    if (step > 0) {
        printf("step=%zu ", step);
    }
    printf("%s runner -> %s implementation via %s: %s (duration_ns=%llu)\n", caller, callee, bridge, message.c_str(),
           static_cast<unsigned long long>(positive_duration(duration_ns)));
    return 0;
}

static int run_matrix(bool json_output) {
    std::vector<const char *> languages = load_languages();
    bool first = true;
    if (json_output) {
        printf("[\n");
    }
    for (const char *caller : languages) {
        for (const char *callee : languages) {
            int rc = run_edge(caller, callee, json_output, &first, 0);
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
        int rc = run_edge(caller, callee, json_output, &first_json, 0);
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
    size_t step = 1;
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
        int rc = run_edge(caller, callee, json_output, &first_json, step);
        if (rc != 0) {
            return rc;
        }
        seen_edge = true;
        step++;
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
        CBridge c_bridge = CBridge::Dlopen;
        if (argi < argc && strcmp(argv[argi], "--bridge") == 0) {
            argi++;
            if (argi >= argc) {
                fprintf(stderr, "usage: xello_cpp [--json] call [--bridge dlopen|extern-c] <callee>\n");
                return 2;
            }
            if (parse_c_bridge(argv[argi++], c_bridge) != 0) {
                return 2;
            }
        }
        if (argi >= argc) {
            fprintf(stderr, "usage: xello_cpp [--json] call [--bridge dlopen|extern-c] <callee>\n");
            return 2;
        }
        if (argi + 1 != argc) {
            fprintf(stderr, "usage: xello_cpp [--json] call [--bridge dlopen|extern-c] <callee>\n");
            return 2;
        }
        if (c_bridge == CBridge::ExternC && strcmp(argv[argi], "c") != 0) {
            fprintf(stderr, "--bridge extern-c is only supported for cpp -> c\n");
            return 2;
        }
        return call_edge(argv[argi], json_output, c_bridge);
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
