try
    using JuliaFormatter
catch err
    if isa(err, ArgumentError)
        println("JuliaFormatter not found; skipping optional formatter")
        exit(0)
    end

    rethrow()
end

format(ARGS)
