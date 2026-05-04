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
	"os/exec"
	"runtime"
	"strings"
	"time"
	"unsafe"
)

var languages = map[string]bool{"python": true, "c": true, "go": true, "rust": true}

type callResult struct {
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
		return "os/exec Python runner"
	case "c":
		return "cgo C ABI fallback"
	case "go":
		return "direct Go function"
	case "rust":
		return "cgo C ABI fallback"
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

func callPython() (string, int64, error) {
	start := time.Now()
	completed := exec.Command("python3", "runners/python/xello_python.py", "--json", "call", "python")
	output, err := completed.Output()
	durationNS := time.Since(start).Nanoseconds()
	if err != nil {
		return "", durationNS, err
	}
	var results []callResult
	if err := json.Unmarshal(output, &results); err != nil {
		return "", durationNS, err
	}
	if len(results) != 1 {
		return "", durationNS, fmt.Errorf("expected one python result, got %d", len(results))
	}
	return strings.Replace(results[0].Message, "called by python", "called by go", 1), durationNS, nil
}

func callProvider(callee string) (string, int64, error) {
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

	caller := C.CString("go")
	defer C.free(unsafe.Pointer(caller))
	start := time.Now()
	message := C.GoString(C.call_hello(symbol, caller))
	return message, max(time.Since(start).Nanoseconds(), 1), nil
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
	case "python":
		message, durationNS, err = callPython()
	case "go":
		start := time.Now()
		message = hello("go")
		durationNS = max(time.Since(start).Nanoseconds(), 1)
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

func delegate(command string, args []string, jsonOutput bool) error {
	commandArgs := []string{}
	if jsonOutput {
		commandArgs = append(commandArgs, "--json")
	}
	commandArgs = append(commandArgs, command)
	commandArgs = append(commandArgs, args...)
	cmd := exec.Command("python3", append([]string{"tools/run_from.py", "python"}, commandArgs...)...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func runnerCommand(language string, args ...string) *exec.Cmd {
	switch language {
	case "python":
		return exec.Command("python3", append([]string{"tools/run_from.py", "python"}, args...)...)
	case "c":
		return exec.Command("build/bin/xello_c", args...)
	case "go":
		return exec.Command("build/bin/xello_go", args...)
	case "rust":
		return exec.Command("build/bin/xello_rust", args...)
	default:
		return nil
	}
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
	cmd := runnerCommand(caller, "--json", "call", callee)
	if cmd == nil {
		return callResult{}, fmt.Errorf("unknown language: %s", caller)
	}
	output, err := cmd.Output()
	if err != nil {
		return callResult{}, err
	}
	var results []callResult
	if err := json.Unmarshal(output, &results); err != nil {
		return callResult{}, err
	}
	if len(results) != 1 {
		return callResult{}, fmt.Errorf("expected one result, got %d", len(results))
	}
	return results[0], nil
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
		results = append(results, result)
	}
	return results, nil
}

func runMatrix() ([]callResult, error) {
	results := make([]callResult, 0, len(languages)*len(languages))
	for _, caller := range []string{"python", "c", "go", "rust"} {
		for _, callee := range []string{"python", "c", "go", "rust"} {
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
	results := make([]callResult, 0, len(languages))
	for _, callee := range []string{"python", "c", "go", "rust"} {
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
