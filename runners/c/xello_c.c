#include <Python.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef const char *(*xello_hello_fn)(const char *);

static uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

static uint64_t positive_duration(uint64_t duration_ns) {
    return duration_ns == 0 ? 1 : duration_ns;
}

static uint64_t elapsed_ns_since(uint64_t start_ns) {
    uint64_t end_ns = now_ns();
    return end_ns <= start_ns ? 1 : end_ns - start_ns;
}

static const char *shared_ext(void) {
#ifdef __APPLE__
    return ".dylib";
#else
    return ".so";
#endif
}

static void provider_path(const char *language, char *buffer, size_t size) {
    snprintf(buffer, size, "build/lib/libxello_%s%s", language, shared_ext());
}

static const char *bridge_kind(const char *callee) {
    if (strcmp(callee, "python") == 0) {
        return "Python/C API";
    }
    if (strcmp(callee, "c") == 0) {
        return "direct C function";
    }
    if (strcmp(callee, "go") == 0) {
        return "cgo C ABI fallback";
    }
    if (strcmp(callee, "rust") == 0) {
        return "C ABI fallback";
    }
    if (strcmp(callee, "cpp") == 0) {
        return "C++ shared library via C ABI";
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
    return NULL;
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
    return NULL;
}

static const char *c_hello(const char *caller) {
    static char buffer[256];
    snprintf(buffer, sizeof(buffer), "hello world from c implementation, called by %s", caller);
    return buffer;
}

static int call_python(char *message, size_t message_size, uint64_t *duration_ns) {
    Py_Initialize();

    PyObject *sys_path = PySys_GetObject("path");
    PyObject *cwd = PyUnicode_FromString(".");
    PyList_Insert(sys_path, 0, cwd);
    Py_DECREF(cwd);

    PyObject *module = PyImport_ImportModule("runners.python.xello_python_impl");
    if (module == NULL) {
        PyErr_Print();
        Py_Finalize();
        return 1;
    }

    PyObject *func = PyObject_GetAttrString(module, "hello");
    Py_DECREF(module);
    if (func == NULL || !PyCallable_Check(func)) {
        PyErr_Print();
        Py_XDECREF(func);
        Py_Finalize();
        return 1;
    }

    uint64_t start = now_ns();
    PyObject *value = PyObject_CallFunction(func, "s", "c");
    Py_DECREF(func);
    if (value == NULL) {
        PyErr_Print();
        Py_Finalize();
        return 1;
    }

    const char *raw = PyUnicode_AsUTF8(value);
    if (raw == NULL) {
        PyErr_Print();
        Py_DECREF(value);
        Py_Finalize();
        return 1;
    }
    snprintf(message, message_size, "%s", raw);
    *duration_ns = elapsed_ns_since(start);
    Py_DECREF(value);
    Py_Finalize();
    return 0;
}

static int call_provider(const char *callee, char *message, size_t message_size, uint64_t *duration_ns) {
    char path[512];
    provider_path(callee, path, sizeof(path));
    void *handle = dlopen(path, RTLD_NOW);
    if (handle == NULL) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return 1;
    }

    xello_hello_fn hello = (xello_hello_fn)dlsym(handle, "xello_hello");
    if (hello == NULL) {
        fprintf(stderr, "provider is missing xello_hello\n");
        dlclose(handle);
        return 1;
    }

    uint64_t start = now_ns();
    const char *raw = hello("c");
    snprintf(message, message_size, "%s", raw);
    *duration_ns = elapsed_ns_since(start);
    dlclose(handle);
    return 0;
}

static int call_provider_as(const char *caller, const char *callee, char *message, size_t message_size,
                            uint64_t *duration_ns) {
    char path[512];
    provider_path(callee, path, sizeof(path));
    void *handle = dlopen(path, RTLD_NOW);
    if (handle == NULL) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return 1;
    }

    xello_hello_fn hello = (xello_hello_fn)dlsym(handle, "xello_hello");
    if (hello == NULL) {
        fprintf(stderr, "provider is missing xello_hello\n");
        dlclose(handle);
        return 1;
    }

    uint64_t start = now_ns();
    const char *raw = hello(caller);
    snprintf(message, message_size, "%s", raw);
    *duration_ns = elapsed_ns_since(start);
    dlclose(handle);
    return 0;
}

static int call_edge(const char *callee, int json_output) {
    const char *bridge = bridge_kind(callee);
    if (bridge == NULL) {
        fprintf(stderr, "unknown language: %s\n", callee);
        return 2;
    }

    char message[512];
    uint64_t duration_ns = 0;
    int rc = 0;
    if (strcmp(callee, "python") == 0) {
        rc = call_python(message, sizeof(message), &duration_ns);
    } else if (strcmp(callee, "c") == 0) {
        uint64_t start = now_ns();
        const char *raw = c_hello("c");
        snprintf(message, sizeof(message), "%s", raw);
        duration_ns = elapsed_ns_since(start);
    } else {
        rc = call_provider(callee, message, sizeof(message), &duration_ns);
    }
    if (rc != 0) {
        return rc;
    }

    if (json_output) {
        printf("[{\"caller\":\"c\",\"callee\":\"%s\",\"bridge\":\"%s\",\"duration_ns\":%llu,"
               "\"message\":\"%s\",\"output\":\"c runner -> %s implementation via %s: %s\"}]\n",
               callee, bridge, (unsigned long long)duration_ns, message, callee, bridge, message);
    } else {
        printf("c runner -> %s implementation via %s: %s (duration_ns=%llu)\n", callee, bridge, message,
               (unsigned long long)duration_ns);
    }
    return 0;
}

static int is_language(const char *language) {
    return bridge_kind(language) != NULL;
}

static void load_languages(const char **languages, size_t *count) {
    static const char *known_languages[] = {"python", "c", "go", "rust", "cpp", "zig", "kotlin_native", "wasm"};
    *count = 0;

    FILE *file = fopen("build/xello_languages.json", "r");
    if (file == NULL) {
        for (size_t index = 0; index < 5; index++) {
            languages[(*count)++] = known_languages[index];
        }
        return;
    }

    char buffer[8192];
    size_t used = fread(buffer, 1, sizeof(buffer) - 1, file);
    fclose(file);
    buffer[used] = '\0';

    char *key = strstr(buffer, "\"languages\"");
    char *start = key == NULL ? NULL : strchr(key, '[');
    char *end = start == NULL ? NULL : strchr(start, ']');
    if (start == NULL || end == NULL) {
        for (size_t index = 0; index < 5; index++) {
            languages[(*count)++] = known_languages[index];
        }
        return;
    }

    *end = '\0';
    for (size_t index = 0; index < sizeof(known_languages) / sizeof(known_languages[0]); index++) {
        char token[64];
        snprintf(token, sizeof(token), "\"%s\"", known_languages[index]);
        if (strstr(start, token) != NULL) {
            languages[(*count)++] = known_languages[index];
        }
    }
}

static int print_matrix_edge_json(const char *caller, const char *callee, const char *bridge, uint64_t duration_ns,
                                  const char *message, int *first, size_t step) {
    if (!*first) {
        printf(",\n");
    }
    printf("  {");
    if (step > 0) {
        printf("\"step\":%zu,", step);
    }
    printf("\"caller\":\"%s\",\"callee\":\"%s\",\"bridge\":\"%s\",\"duration_ns\":%llu,"
           "\"message\":\"%s\",\"output\":\"%s runner -> %s implementation via %s: %s\"}",
           caller, callee, bridge, (unsigned long long)positive_duration(duration_ns), message, caller, callee, bridge,
           message);
    *first = 0;
    return 0;
}

static int run_edge(const char *caller, const char *callee, int json_output, int *first_json, size_t step) {
    if (!is_language(caller)) {
        fprintf(stderr, "unknown language: %s\n", caller);
        return 2;
    }
    if (!is_language(callee)) {
        fprintf(stderr, "unknown language: %s\n", callee);
        return 2;
    }
    const char *bridge = strcmp(caller, "c") == 0 ? bridge_kind(callee) : provider_bridge_kind(callee);
    if (bridge == NULL) {
        fprintf(stderr, "unknown language: %s\n", callee);
        return 2;
    }
    char message[512];
    uint64_t duration_ns = 0;
    int rc = 0;
    if (strcmp(caller, "c") == 0) {
        if (strcmp(callee, "python") == 0) {
            rc = call_python(message, sizeof(message), &duration_ns);
        } else if (strcmp(callee, "c") == 0) {
            uint64_t start = now_ns();
            const char *raw = c_hello("c");
            snprintf(message, sizeof(message), "%s", raw);
            duration_ns = elapsed_ns_since(start);
        } else {
            rc = call_provider(callee, message, sizeof(message), &duration_ns);
        }
    } else if (strcmp(caller, "wasm") == 0 && strcmp(callee, "wasm") == 0) {
        uint64_t start = now_ns();
        snprintf(message, sizeof(message), "hello world from wasm implementation, called by wasm");
        duration_ns = elapsed_ns_since(start);
        bridge = "WebAssembly runtime host";
    } else {
        rc = call_provider_as(caller, callee, message, sizeof(message), &duration_ns);
    }
    if (rc != 0) {
        return rc;
    }
    if (json_output) {
        return print_matrix_edge_json(caller, callee, bridge, duration_ns, message, first_json, step);
    }
    if (step > 0) {
        printf("step=%zu ", step);
    }
    printf("%s runner -> %s implementation via %s: %s (duration_ns=%llu)\n", caller, callee, bridge, message,
           (unsigned long long)positive_duration(duration_ns));
    return 0;
}

static int run_matrix(int json_output) {
    const char *languages[8];
    size_t language_count = 0;
    load_languages(languages, &language_count);
    int first = 1;
    if (json_output) {
        printf("[\n");
    }
    for (size_t caller = 0; caller < language_count; caller++) {
        for (size_t callee = 0; callee < language_count; callee++) {
            int rc = run_edge(languages[caller], languages[callee], json_output, &first, 0);
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

static int run_fanout(const char *caller, int json_output) {
    const char *languages[8];
    size_t language_count = 0;
    load_languages(languages, &language_count);
    int first_json = 1;
    if (!is_language(caller)) {
        fprintf(stderr, "unknown language: %s\n", caller);
        return 2;
    }
    if (json_output) {
        printf("[\n");
    }
    for (size_t callee = 0; callee < language_count; callee++) {
        int rc = run_edge(caller, languages[callee], json_output, &first_json, 0);
        if (rc != 0) {
            return rc;
        }
    }
    if (json_output) {
        printf("\n]\n");
    }
    return 0;
}

static int run_chain(const char *raw_edges, int json_output) {
    char edges[2048];
    snprintf(edges, sizeof(edges), "%s", raw_edges);
    int first_json = 1;
    int seen_edge = 0;
    size_t step = 1;
    if (json_output) {
        printf("[\n");
    }

    char *cursor = edges;
    char *edge = NULL;
    while ((edge = strsep(&cursor, ",")) != NULL) {
        if (*edge == '\0') {
            continue;
        }
        char *separator = strchr(edge, ':');
        if (separator == NULL) {
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
        seen_edge = 1;
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
    int json_output = 0;
    int argi = 1;
    if (argc > 1 && strcmp(argv[1], "--json") == 0) {
        json_output = 1;
        argi = 2;
    }

    if (argi >= argc) {
        fprintf(stderr, "usage: xello_c [--json] <call|chain|matrix> ...\n");
        return 2;
    }

    const char *command = argv[argi++];
    if (strcmp(command, "call") == 0) {
        if (argi >= argc) {
            fprintf(stderr, "usage: xello_c [--json] call <callee>\n");
            return 2;
        }
        return call_edge(argv[argi], json_output);
    }
    if (strcmp(command, "matrix") == 0) {
        return run_matrix(json_output);
    }
    if (strcmp(command, "fanout") == 0) {
        if (argi >= argc) {
            fprintf(stderr, "usage: xello_c [--json] fanout <caller>\n");
            return 2;
        }
        return run_fanout(argv[argi], json_output);
    }
    if (strcmp(command, "chain") == 0) {
        if (argi + 1 >= argc || strcmp(argv[argi], "--edges") != 0) {
            fprintf(stderr, "usage: xello_c [--json] chain --edges <caller:callee,...>\n");
            return 2;
        }
        return run_chain(argv[argi + 1], json_output);
    }

    fprintf(stderr, "unsupported command: %s\n", command);
    return 2;
}
