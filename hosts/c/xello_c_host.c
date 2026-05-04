#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef const char *(*xello_hello_fn)(const char *);
typedef const char *(*xello_language_fn)(void);

static uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

int main(int argc, char **argv) {
    int json_output = 0;
    const char *provider_path = NULL;

    if (argc == 2) {
        provider_path = argv[1];
    } else if (argc == 3 && strcmp(argv[1], "--json") == 0) {
        json_output = 1;
        provider_path = argv[2];
    } else {
        fprintf(stderr, "usage: %s [--json] <provider-library>\n", argv[0]);
        return 2;
    }

    void *handle = dlopen(provider_path, RTLD_NOW);
    if (handle == NULL) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return 1;
    }

    xello_hello_fn hello = (xello_hello_fn)dlsym(handle, "xello_hello");
    xello_language_fn language = (xello_language_fn)dlsym(handle, "xello_language");
    if (hello == NULL || language == NULL) {
        fprintf(stderr, "provider is missing required xello symbols\n");
        dlclose(handle);
        return 1;
    }

    const char *provider = language();
    uint64_t start = now_ns();
    const char *message = hello("c");
    uint64_t duration_ns = now_ns() - start;
    if (duration_ns == 0) {
        duration_ns = 1;
    }

    if (json_output) {
        printf(
            "{\"caller\":\"c\",\"callee\":\"%s\",\"duration_ns\":%llu,\"output\":\"c host -> %s provider: %s\"}\n",
            provider,
            (unsigned long long)duration_ns,
            provider,
            message);
    } else {
        printf("c host -> %s provider: %s (duration_ns=%llu)\n", provider, message, (unsigned long long)duration_ns);
    }

    dlclose(handle);
    return 0;
}
