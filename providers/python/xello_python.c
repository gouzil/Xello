#include "xello.h"

#include <Python.h>
#include <stdio.h>

static PyObject *hello_func = NULL;
static char message_buffer[512];

const char *xello_language(void) {
    return "python";
}

static int ensure_python_provider(void) {
    if (!Py_IsInitialized()) {
        Py_Initialize();
    }

    if (hello_func != NULL) {
        return 0;
    }

    PyObject *sys_path = PySys_GetObject("path");
    if (sys_path == NULL) {
        PyErr_Print();
        return 1;
    }

    PyObject *cwd = PyUnicode_FromString(".");
    if (cwd == NULL) {
        PyErr_Print();
        return 1;
    }
    if (PyList_Insert(sys_path, 0, cwd) != 0) {
        Py_DECREF(cwd);
        PyErr_Print();
        return 1;
    }
    Py_DECREF(cwd);

    PyObject *module = PyImport_ImportModule("runners.python.xello_python_impl");
    if (module == NULL) {
        PyErr_Print();
        return 1;
    }

    hello_func = PyObject_GetAttrString(module, "hello");
    Py_DECREF(module);
    if (hello_func == NULL || !PyCallable_Check(hello_func)) {
        Py_XDECREF(hello_func);
        hello_func = NULL;
        PyErr_Print();
        return 1;
    }

    return 0;
}

const char *xello_hello(const char *caller) {
    const char *safe_caller = caller == NULL ? "unknown" : caller;

    if (!Py_IsInitialized()) {
        Py_Initialize();
    }
    PyGILState_STATE gil = PyGILState_Ensure();

    if (ensure_python_provider() != 0) {
        snprintf(message_buffer, sizeof(message_buffer), "python provider failed");
        PyGILState_Release(gil);
        return message_buffer;
    }

    PyObject *value = PyObject_CallFunction(hello_func, "s", safe_caller);
    if (value == NULL) {
        PyErr_Print();
        snprintf(message_buffer, sizeof(message_buffer), "python provider failed");
        PyGILState_Release(gil);
        return message_buffer;
    }

    const char *raw = PyUnicode_AsUTF8(value);
    if (raw == NULL) {
        PyErr_Print();
        Py_DECREF(value);
        snprintf(message_buffer, sizeof(message_buffer), "python provider failed");
        PyGILState_Release(gil);
        return message_buffer;
    }

    snprintf(message_buffer, sizeof(message_buffer), "%s", raw);
    Py_DECREF(value);
    PyGILState_Release(gil);
    return message_buffer;
}
