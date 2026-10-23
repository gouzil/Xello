#define _GNU_SOURCE
#include "xello.h"

#include <Python.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *message = NULL;

// Python extensions need global symbols, and V8's Python threads outlive dlclose.
__attribute__((constructor)) static void keep_python_runtime_loaded(void) {
    Dl_info image;
    if (!dladdr((const void *)Py_Initialize, &image)) {
        fprintf(stderr, "cannot locate the Python runtime\n");
        abort();
    }
    void *runtime = dlopen(image.dli_fname, RTLD_NOW | RTLD_GLOBAL | RTLD_NODELETE);
    if (runtime == NULL) {
        fprintf(stderr, "cannot keep the Python runtime loaded: %s\n", dlerror());
        abort();
    }
    dlclose(runtime);
}

__attribute__((destructor)) static void cleanup(void) {
    free(message);
}

const char *xello_language(void) {
    return "moonbit";
}

const char *xello_hello(const char *caller) {
    if (!Py_IsInitialized()) {
        Py_Initialize();
    }
    PyGILState_STATE gil = PyGILState_Ensure();
    PyObject *path = PySys_GetObject("path");
    PyObject *cwd = PyUnicode_FromString(".");
    int present = path == NULL || cwd == NULL ? -1 : PySequence_Contains(path, cwd);
    if (present < 0 || (present == 0 && PyList_Insert(path, 0, cwd) != 0)) {
        PyErr_Print();
        exit(1);
    }
    Py_DECREF(cwd);
    PyObject *module = PyImport_ImportModule("providers.moonbit.vm_provider");
    PyObject *function = module == NULL ? NULL : PyObject_GetAttrString(module, "hello");
    Py_XDECREF(module);
    const char *safe_caller = caller == NULL ? "unknown" : caller;
    PyObject *caller_value = PyUnicode_DecodeUTF8(safe_caller, strlen(safe_caller), "replace");
    PyObject *result = function == NULL || caller_value == NULL
                           ? NULL
                           : PyObject_CallFunction(function, "sO", XELLO_MOONBIT_BACKEND, caller_value);
    Py_XDECREF(caller_value);
    Py_XDECREF(function);
    const char *raw = result == NULL ? NULL : PyUnicode_AsUTF8(result);
    if (raw == NULL) {
        PyErr_Print();
        exit(1);
    }
    char *copy = strdup(raw);
    Py_DECREF(result);
    if (copy == NULL) {
        fprintf(stderr, "cannot allocate MoonBit provider message\n");
        exit(1);
    }
    free(message);
    message = copy;
    PyGILState_Release(gil);
    return message;
}
