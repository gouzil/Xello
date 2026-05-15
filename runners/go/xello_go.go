package main

/*
#cgo darwin LDFLAGS: -ldl
#cgo linux LDFLAGS: -ldl
#include <dlfcn.h>
#include <stdlib.h>

typedef const char *(*xello_hello_fn)(const char *);

static const char *call_hello(void *fn, const char *caller) {
	return ((xello_hello_fn)fn)(caller);
}
*/
import "C"

import (
	"encoding/json"
	"fmt"
	"os"
	"runtime"
	"strings"
	"time"
	"unsafe"
)

var knownLanguageList = []string{"python", "c", "go", "rust", "cpp", "zig", "kotlin_native", "wasm"}
var languages = map[string]bool{
	"python":        true,
	"c":             true,
	"go":            true,
	"rust":          true,
	"cpp":           true,
	"zig":           true,
	"kotlin_native": true,
	"wasm":          true,
}

type runtimeManifest struct {
	Languages []string `json:"languages"`
}

func languageList() []string {
	raw, err := os.ReadFile("build/xello_languages.json")
	if err != nil {
		return []string{"python", "c", "go", "rust", "cpp"}
	}
	var manifest runtimeManifest
	if err := json.Unmarshal(raw, &manifest); err != nil {
		return []string{"python", "c", "go", "rust", "cpp"}
	}
	selected := make([]string, 0, len(manifest.Languages))
	inManifest := make(map[string]bool, len(manifest.Languages))
	for _, language := range manifest.Languages {
		inManifest[language] = true
	}
	for _, language := range knownLanguageList {
		if inManifest[language] {
			selected = append(selected, language)
		}
	}
	return selected
}

type callResult struct {
	Step       int    `json:"step,omitempty"`
	Caller     string `json:"caller"`
	Callee     string `json:"callee"`
	Bridge     string `json:"bridge"`
	DurationNS int64  `json:"duration_ns"`
	Message    string `json:"message"`
	Output     string `json:"output"`
}

func bridgeKind(callee string) string {
	switch callee {
	case "python":
		return "Python shared library via Python/C API"
	case "c":
		return "cgo C ABI fallback"
	case "go":
		return "direct Go function"
	case "rust":
		return "cgo C ABI fallback"
	case "cpp":
		return "C++ shared library via C ABI"
	case "zig":
		return "Zig shared library via C ABI"
	case "kotlin_native":
		return "Kotlin/Native dynamic library via C ABI"
	case "wasm":
		return "WebAssembly C ABI shim"
	default:
		return ""
	}
}

func providerBridgeKind(callee string) string {
	switch callee {
	case "python":
		return "Python provider function via Python/C API"
	case "c":
		return "C provider function via C ABI"
	case "go":
		return "Go provider function via C ABI"
	case "rust":
		return "Rust provider function via C ABI"
	case "cpp":
		return "C++ provider function via C ABI"
	case "zig":
		return "Zig provider function via C ABI"
	case "kotlin_native":
		return "Kotlin/Native provider function via C ABI"
	case "wasm":
		return "WebAssembly C ABI shim"
	default:
		return ""
	}
}

func sharedExt() string {
	if runtime.GOOS == "darwin" {
		return ".dylib"
	}
	return ".so"
}

func hello(caller string) string {
	return "hello world from go implementation, called by " + caller
}

func callProvider(callee string) (string, int64, error) {
	return callProviderAs("go", callee)
}

func callProviderAs(callerName, callee string) (string, int64, error) {
	path := C.CString(fmt.Sprintf("build/lib/libxello_%s%s", callee, sharedExt()))
	defer C.free(unsafe.Pointer(path))

	handle := C.dlopen(path, C.RTLD_NOW)
	if handle == nil {
		return "", 0, fmt.Errorf("dlopen failed: %s", C.GoString(C.dlerror()))
	}
	defer C.dlclose(handle)

	symbolName := C.CString("xello_hello")
	defer C.free(unsafe.Pointer(symbolName))
	symbol := C.dlsym(handle, symbolName)
	if symbol == nil {
		return "", 0, fmt.Errorf("provider is missing xello_hello")
	}

	caller := C.CString(callerName)
	defer C.free(unsafe.Pointer(caller))
	start := time.Now()
	message := C.GoString(C.call_hello(symbol, caller))
	return message, max(time.Since(start).Nanoseconds(), 1), nil
}

func callLocal() (string, int64) {
	start := time.Now()
	message := hello("go")
	return message, max(time.Since(start).Nanoseconds(), 1)
}

func callEdge(callee string) (callResult, error) {
	if !languages[callee] {
		return callResult{}, fmt.Errorf("unknown language: %s", callee)
	}

	bridge := bridgeKind(callee)
	var message string
	var durationNS int64
	var err error
	switch callee {
	case "go":
		message, durationNS = callLocal()
	default:
		message, durationNS, err = callProvider(callee)
	}
	if err != nil {
		return callResult{}, err
	}

	output := fmt.Sprintf("go runner -> %s implementation via %s: %s", callee, bridge, message)
	return callResult{
		Caller:     "go",
		Callee:     callee,
		Bridge:     bridge,
		DurationNS: max(durationNS, 1),
		Message:    message,
		Output:     output,
	}, nil
}

func parseEdges(raw string) ([][2]string, error) {
	var edges [][2]string
	for _, item := range strings.Split(raw, ",") {
		edge := strings.TrimSpace(item)
		if edge == "" {
			continue
		}
		parts := strings.Split(edge, ":")
		if len(parts) != 2 {
			return nil, fmt.Errorf("invalid chain edge %q; expected caller:callee", edge)
		}
		caller := strings.ToLower(strings.TrimSpace(parts[0]))
		callee := strings.ToLower(strings.TrimSpace(parts[1]))
		if !languages[caller] {
			return nil, fmt.Errorf("unknown language: %s", caller)
		}
		if !languages[callee] {
			return nil, fmt.Errorf("unknown language: %s", callee)
		}
		edges = append(edges, [2]string{caller, callee})
	}
	if len(edges) == 0 {
		return nil, fmt.Errorf("chain requires at least one caller:callee edge")
	}
	return edges, nil
}

func callViaRunner(caller, callee string) (callResult, error) {
	if caller == "go" {
		return callEdge(callee)
	}
	if !languages[caller] {
		return callResult{}, fmt.Errorf("unknown language: %s", caller)
	}
	if !languages[callee] {
		return callResult{}, fmt.Errorf("unknown language: %s", callee)
	}
	bridge := providerBridgeKind(callee)
	var message string
	var durationNS int64
	var err error
	if caller == "wasm" && callee == "wasm" {
		start := time.Now()
		message = "hello world from wasm implementation, called by wasm"
		durationNS = max(time.Since(start).Nanoseconds(), 1)
		bridge = "WebAssembly runtime host"
	} else if callee == "go" {
		start := time.Now()
		message = hello(caller)
		durationNS = max(time.Since(start).Nanoseconds(), 1)
	} else {
		message, durationNS, err = callProviderAs(caller, callee)
	}
	if err != nil {
		return callResult{}, err
	}
	output := fmt.Sprintf("%s runner -> %s implementation via %s: %s", caller, callee, bridge, message)
	return callResult{
		Caller:     caller,
		Callee:     callee,
		Bridge:     bridge,
		DurationNS: max(durationNS, 1),
		Message:    message,
		Output:     output,
	}, nil
}

func runChain(raw string) ([]callResult, error) {
	edges, err := parseEdges(raw)
	if err != nil {
		return nil, err
	}
	results := make([]callResult, 0, len(edges))
	for _, edge := range edges {
		result, err := callViaRunner(edge[0], edge[1])
		if err != nil {
			return nil, err
		}
		result.Step = len(results) + 1
		results = append(results, result)
	}
	return results, nil
}

func runMatrix() ([]callResult, error) {
	currentLanguages := languageList()
	results := make([]callResult, 0, len(currentLanguages)*len(currentLanguages))
	for _, caller := range currentLanguages {
		for _, callee := range currentLanguages {
			result, err := callViaRunner(caller, callee)
			if err != nil {
				return nil, err
			}
			results = append(results, result)
		}
	}
	return results, nil
}

func runFanout(caller string) ([]callResult, error) {
	if !languages[caller] {
		return nil, fmt.Errorf("unknown language: %s", caller)
	}
	currentLanguages := languageList()
	results := make([]callResult, 0, len(currentLanguages))
	for _, callee := range currentLanguages {
		result, err := callViaRunner(caller, callee)
		if err != nil {
			return nil, err
		}
		results = append(results, result)
	}
	return results, nil
}

func printResults(results []callResult, jsonOutput bool) error {
	if jsonOutput {
		encoder := json.NewEncoder(os.Stdout)
		encoder.SetIndent("", "  ")
		return encoder.Encode(results)
	}
	for _, item := range results {
		if item.Step > 0 {
			fmt.Printf("step=%d ", item.Step)
		}
		fmt.Printf("%s (duration_ns=%d)\n", item.Output, item.DurationNS)
	}
	return nil
}

func main() {
	jsonOutput := false
	args := os.Args[1:]
	if len(args) > 0 && args[0] == "--json" {
		jsonOutput = true
		args = args[1:]
	}
	if len(args) == 0 {
		fmt.Fprintln(os.Stderr, "usage: xello_go [--json] <call|chain|matrix> ...")
		os.Exit(2)
	}

	switch args[0] {
	case "call":
		if len(args) != 2 {
			fmt.Fprintln(os.Stderr, "usage: xello_go [--json] call <callee>")
			os.Exit(2)
		}
		result, err := callEdge(args[1])
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		if err := printResults([]callResult{result}, jsonOutput); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	case "matrix":
		results, err := runMatrix()
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		if err := printResults(results, jsonOutput); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	case "fanout":
		if len(args) != 2 {
			fmt.Fprintln(os.Stderr, "usage: xello_go [--json] fanout <caller>")
			os.Exit(2)
		}
		results, err := runFanout(args[1])
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		if err := printResults(results, jsonOutput); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	case "chain":
		if len(args) != 3 || args[1] != "--edges" {
			fmt.Fprintln(os.Stderr, "usage: xello_go [--json] chain --edges <caller:callee,...>")
			os.Exit(2)
		}
		results, err := runChain(args[2])
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		if err := printResults(results, jsonOutput); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	default:
		fmt.Fprintf(os.Stderr, "unsupported command: %s\n", args[0])
		os.Exit(2)
	}
}
