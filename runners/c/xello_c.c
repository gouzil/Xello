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
    *duration_ns = positive_duration(now_ns() - start);
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
    *duration_ns = positive_duration(now_ns() - start);
    snprintf(message, message_size, "%s", raw);
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
        snprintf(message, sizeof(message), "%s", c_hello("c"));
        duration_ns = positive_duration(now_ns() - start);
    } else {
        rc = call_provider(callee, message, sizeof(message), &duration_ns);
    }
    if (rc != 0) {
        return rc;
    }

    if (json_output) {
        printf(
            "[{\"caller\":\"c\",\"callee\":\"%s\",\"bridge\":\"%s\",\"duration_ns\":%llu,"
            "\"message\":\"%s\",\"output\":\"c runner -> %s implementation via %s: %s\"}]\n",
            callee,
            bridge,
            (unsigned long long)duration_ns,
            message,
            callee,
            bridge,
            message);
    } else {
        printf("c runner -> %s implementation via %s: %s (duration_ns=%llu)\n",
               callee,
               bridge,
               message,
               (unsigned long long)duration_ns);
    }
    return 0;
}

static int is_language(const char *language) {
    return strcmp(language, "python") == 0 || strcmp(language, "c") == 0 || strcmp(language, "go") == 0 ||
           strcmp(language, "rust") == 0;
}

static void edge_command(const char *caller, const char *callee, int json_output, char *buffer, size_t size) {
    const char *json_flag = json_output ? "--json " : "";
    if (strcmp(caller, "python") == 0) {
        snprintf(buffer, size, "python3 tools/run_from.py python %scall %s", json_flag, callee);
    } else if (strcmp(caller, "c") == 0) {
        snprintf(buffer, size, "build/bin/xello_c %scall %s", json_flag, callee);
    } else if (strcmp(caller, "go") == 0) {
        snprintf(buffer, size, "build/bin/xello_go %scall %s", json_flag, callee);
    } else {
        snprintf(buffer, size, "build/bin/xello_rust %scall %s", json_flag, callee);
    }
}

static int run_edge_command_json(const char *caller, const char *callee, int *first) {
    char command[512];
    edge_command(caller, callee, 1, command, sizeof(command));

    FILE *pipe = popen(command, "r");
    if (pipe == NULL) {
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
    if (start == NULL || end == NULL || end <= start) {
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
    *first = 0;
    return 0;
}

static int run_edge_command_human(const char *caller, const char *callee) {
    char command[512];
    edge_command(caller, callee, 0, command, sizeof(command));
    int rc = system(command);
    if (rc != 0) {
        fprintf(stderr, "runner command failed: %s\n", command);
        return 1;
    }
    return 0;
}

static int run_edge(const char *caller, const char *callee, int json_output, int *first_json) {
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

static int run_matrix(int json_output) {
    const char *languages[] = {"python", "c", "go", "rust"};
    int first = 1;
    if (json_output) {
        printf("[\n");
    }
    for (size_t caller = 0; caller < 4; caller++) {
        for (size_t callee = 0; callee < 4; callee++) {
            int rc = run_edge(languages[caller], languages[callee], json_output, &first);
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
    const char *languages[] = {"python", "c", "go", "rust"};
    int first_json = 1;
    if (!is_language(caller)) {
        fprintf(stderr, "unknown language: %s\n", caller);
        return 2;
    }
    if (json_output) {
        printf("[\n");
    }
    for (size_t callee = 0; callee < 4; callee++) {
        int rc = run_edge(caller, languages[callee], json_output, &first_json);
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
        int rc = run_edge(caller, callee, json_output, &first_json);
        if (rc != 0) {
            return rc;
        }
        seen_edge = 1;
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
