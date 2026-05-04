package main

/*
#cgo darwin LDFLAGS: -ldl
#cgo linux LDFLAGS: -ldl
#include <dlfcn.h>
#include <stdlib.h>

typedef const char *(*xello_hello_fn)(const char *);
typedef const char *(*xello_language_fn)(void);

static const char *call_hello(void *fn, const char *caller) {
	return ((xello_hello_fn)fn)(caller);
}

static const char *call_language(void *fn) {
	return ((xello_language_fn)fn)();
}
*/
import "C"

import (
	"encoding/json"
	"fmt"
	"os"
	"time"
	"unsafe"
)

type callResult struct {
	Caller     string `json:"caller"`
	Callee     string `json:"callee"`
	DurationNS int64  `json:"duration_ns"`
	Output     string `json:"output"`
}

func main() {
	jsonOutput := false
	var providerPath string
	if len(os.Args) == 2 {
		providerPath = os.Args[1]
	} else if len(os.Args) == 3 && os.Args[1] == "--json" {
		jsonOutput = true
		providerPath = os.Args[2]
	} else {
		fmt.Fprintf(os.Stderr, "usage: %s [--json] <provider-library>\n", os.Args[0])
		os.Exit(2)
	}

	path := C.CString(providerPath)
	defer C.free(unsafe.Pointer(path))

	handle := C.dlopen(path, C.RTLD_NOW)
	if handle == nil {
		fmt.Fprintf(os.Stderr, "dlopen failed: %s\n", C.GoString(C.dlerror()))
		os.Exit(1)
	}
	defer C.dlclose(handle)

	helloName := C.CString("xello_hello")
	languageName := C.CString("xello_language")
	defer C.free(unsafe.Pointer(helloName))
	defer C.free(unsafe.Pointer(languageName))

	hello := C.dlsym(handle, helloName)
	language := C.dlsym(handle, languageName)
	if hello == nil || language == nil {
		fmt.Fprintln(os.Stderr, "provider is missing required xello symbols")
		os.Exit(1)
	}

	caller := C.CString("go")
	defer C.free(unsafe.Pointer(caller))

	provider := C.GoString(C.call_language(language))
	start := time.Now()
	message := C.GoString(C.call_hello(hello, caller))
	durationNS := time.Since(start).Nanoseconds()
	if durationNS == 0 {
		durationNS = 1
	}
	output := fmt.Sprintf("go host -> %s provider: %s", provider, message)

	if jsonOutput {
		encoder := json.NewEncoder(os.Stdout)
		if err := encoder.Encode(callResult{
			Caller:     "go",
			Callee:     provider,
			DurationNS: durationNS,
			Output:     output,
		}); err != nil {
			fmt.Fprintf(os.Stderr, "json encode failed: %v\n", err)
			os.Exit(1)
		}
		return
	}

	fmt.Printf("%s (duration_ns=%d)\n", output, durationNS)
}
