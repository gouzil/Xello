#include <dlfcn.h>
#include <moonbit.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef const char *(*xello_hello_fn)(const char *);

static void die(const char *message) {
    fprintf(stderr, "%s\n", message);
    exit(1);
}

int64_t xello_moonbit_now_ns(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        die("cannot read monotonic clock");
    }
    return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

void xello_moonbit_fail(moonbit_bytes_t message, int32_t status) {
    fwrite(message, 1, Moonbit_array_length(message), stderr);
    fputc('\n', stderr);
    exit(status);
}

moonbit_bytes_t xello_moonbit_read_manifest(void) {
    FILE *file = fopen("build/xello_languages.json", "rb");
    if (file == NULL) {
        die("cannot open build/xello_languages.json; run tools/build.py first");
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        die("cannot seek language manifest");
    }
    long size = ftell(file);
    if (size < 0 || size > INT32_MAX || fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        die("invalid language manifest size");
    }
    moonbit_bytes_t result = moonbit_make_bytes_raw((int32_t)size);
    size_t count = fread(result, 1, (size_t)size, file);
    int failed = ferror(file);
    fclose(file);
    if (count != (size_t)size || failed) {
        moonbit_decref(result);
        die("cannot read language manifest");
    }
    return result;
}

moonbit_bytes_t xello_moonbit_call_provider(moonbit_bytes_t caller, moonbit_bytes_t callee, int64_t *duration) {
#ifdef __APPLE__
    const char *ext = ".dylib";
#else
    const char *ext = ".so";
#endif
    char path[512];
    int length = snprintf(path, sizeof(path), "build/lib/libxello_%s%s", (const char *)callee, ext);
    if (length < 0 || (size_t)length >= sizeof(path)) {
        die("provider path is too long");
    }
    void *handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (handle == NULL) {
        die(dlerror());
    }
    xello_hello_fn hello = (xello_hello_fn)dlsym(handle, "xello_hello");
    if (hello == NULL) {
        dlclose(handle);
        die("provider is missing xello_hello");
    }
    int64_t start = xello_moonbit_now_ns();
    const char *raw = hello((const char *)caller);
    *duration = xello_moonbit_now_ns() - start;
    if (raw == NULL) {
        dlclose(handle);
        die("provider returned a null message");
    }
    size_t size = strlen(raw);
    if (size > INT32_MAX) {
        dlclose(handle);
        die("provider message exceeds the runtime byte limit");
    }
    moonbit_bytes_t result = moonbit_make_bytes_raw((int32_t)size);
    memcpy(result, raw, size);
    dlclose(handle);
    return result;
}
