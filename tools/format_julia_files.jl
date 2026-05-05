try
    using JuliaFormatter
catch err
    @error "JuliaFormatter is required for Julia formatting: import Pkg; Pkg.add(\"JuliaFormatter\")" exception=(err, catch_backtrace())
    exit(1)
end

format(ARGS)
