---
type: specification
project: Crabwalk
status: proposed
version: 0.1-draft
created: 2026-08-21
updated: 2026-08-21
tags:
  - project/crabwalk
  - area/product
  - area/language-semantics
---

# Crabwalk Product Contract

> [!note] Status
> This note converts [[crabwalk|the guiding architecture]] into an implementable release contract. The architecture brief remains the source of product intent. Where it deliberately leaves syntax or behavior open, this note supplies a narrow provisional default that must be accepted or revised through [[Crabwalk Risks and Decisions#Decision protocol|the decision protocol]].

## Contract hierarchy

When two documents appear to conflict:

1. The architectural rules in [[crabwalk#50. Crabwalk Architectural Rules]] win.
2. An accepted ADR wins over a provisional recommendation.
3. The active milestone contract wins over future-roadmap examples.
4. Tests are executable evidence of the active contract, but a mistaken test does not silently redefine it.

## Non-negotiable product invariants

1. Source is valid Python syntax and uses Python files, packages, and imports.
2. The canonical user import is from crabwalk import rust.
3. Rust participation is explicit.
4. A rust.fn function either compiles as Rust or produces a compilation error.
5. No unsupported Rust island silently falls back to Python execution.
6. Rust types denote real Rust types and behavior, not Python imitations.
7. Python calls and data conversions are legal only when the active contract supports them, and each is visible to tooling.
8. Cargo resolves Rust dependencies; rustc performs Rust type, ownership, borrow, and safety checking.
9. Generated Rust is deterministic and inspectable.
10. The primary diagnostic location is the original Python source.
11. The compiler emits safe Rust for the supported surface.
12. Python code outside Rust islands remains ordinary Python.

## Release boundaries

The original brief uses “MVP” for a broad capability set. Delivery separates that set into smaller gates so architecture is proven before breadth is added.

| Boundary | Purpose | Included | Explicitly excluded |
|---|---|---|---|
| M1 technical proof | Prove the whole compiler/runtime path | rust.fn, u64 parameters/returns, integer literals, names, subtraction/addition, comparison, if, return, same-function recursion, primitive ABI, expand/build/cache/error path | General loops, containers, crates, arbitrary Python calls, ownership wrappers |
| M2 core compiler | Establish a useful typed Rust island | Numeric primitives, bool, unit, locals, control flow, local function calls, String/Str, Vec, Option, basic Result, selected std symbols | Third-party crates, Rust-owned Python objects, structs/enums, async |
| M3 v0.1 alpha | Make the core safe to use and diagnose | Explicit conversions, first Python call boundary, source-mapped errors, cache hardening, inspect/show/check/build/doctor, packaging prototype | General crate reflection, arbitrary dynamic Python, ownership across Python |
| M4 ecosystem alpha | Validate the crate model | Static rust.crate declarations, Cargo features and lock policy, path lowering, one ordinary crates.io demonstration | General macros and automatic understanding of every crate API |
| M5 ownership preview | Deliver the core semantic differentiator | Owned/Ref/Mut lowering, generated concrete wrappers, move-state enforcement across Python | Long-lived borrowed Python views, unsound aliasing shortcuts |
| M6 domain preview | Support meaningful Rust models | rust.struct, rust.enum, construction, fields, pattern matching subset, selected derives | Traits as a general authoring surface |

## M1 executable contract

The M1 compiler accepts exactly the forms required by the Fibonacci proof:

- One Python source module.
- from crabwalk import rust.
- Module-level functions decorated with rust.fn.
- Positional parameters with rust.u64 annotations.
- A rust.u64 return annotation.
- Integer literals that fit their contextual type.
- Local name reads.
- Binary addition and subtraction on u64.
- A single comparison using <=.
- if with a required boolean condition.
- return on all reachable paths.
- A direct call to the same rust.fn for recursion.
- A Python caller passing and receiving a checked integer.

Everything else inside rust.fn is rejected with CRAB102 Unsupported construct, not ignored and not executed as Python.

### M1 required demonstrations

1. fibonacci(40) returns the expected result through a normal Python call.
2. Generated Rust contains a native recursive function; recursion does not call back into Python.
3. Passing a negative Python integer or a value above u64 range fails before native execution with a clear Python exception.
4. Removing a return path produces a source-located diagnostic.
5. Adding an unsupported list comprehension produces CRAB102 at that expression.
6. A deliberately ill-typed accepted expression preserves the rustc error code and points primarily to the Python expression.
7. A second unchanged process uses the artifact cache and executes no Cargo command.

## v0.1 source surface

The tables below are the target contract for M2 and M3. “Deferred” means the parser may recognize the Python node, but validation must reject it.

### Declarations and signatures

| Source form | v0.1 behavior |
|---|---|
| from crabwalk import rust | Required canonical namespace; aliases are rejected initially so diagnostics and static discovery stay deterministic. |
| @rust.fn | Supported on module-level functions only. It is invalid on nested functions, methods, async functions, or dynamically created callables. |
| Parameter annotations | Required on every parameter. They must resolve statically to a supported Rust type. |
| Return annotation | Required for value-returning functions. None denotes Rust unit. A missing annotation is accepted only for a function proven to return no value. |
| Positional parameters | Supported. |
| Keyword-only parameters, positional-only markers, defaults, variadics | Deferred. |
| Type variables and user generics | Deferred. |
| Other decorators on rust.fn | Deferred because decorator order can change identity and behavior. |
| Nested functions, closures, lambdas | Deferred. |
| Module constants | Literal typed constants may be added late in M2; mutable Python globals and captured objects are rejected. |

Crabwalk parses annotations from source. It does not depend on runtime evaluation of function.__annotations__, which avoids import side effects and annotation-runtime differences between Python releases.

### Types

| Type | Rust meaning | Python boundary in v0.1 |
|---|---|---|
| rust.i8 through rust.i128 | Matching signed integer | Checked Python int conversion |
| rust.u8 through rust.u128 | Matching unsigned integer | Checked Python int conversion |
| rust.f32, rust.f64 | Matching float | Checked Python int/float input; Python float output |
| rust.bool | bool | Python bool only; int-as-bool coercion is rejected |
| None return | () | Returns Python None |
| rust.String | Owned String | Python str conversion with visible allocation |
| rust.Str | Borrowed &str | Parameter or local borrow only; never returned or stored in v0.1 |
| rust.Vec[T] | Vec<T> for a supported concrete T | Python sequence conversion is explicit and allocating in v0.1 |
| rust.Option[T] | Option<T> | None ↔ None; Some value follows T conversion |
| rust.Result[T, E] | Result<T, E> | Remains native inside an island; exported Err uses the provisional error policy below |

Box, Rc, Arc, HashMap, HashSet, user structs, enums, traits, and explicit Owned/Ref/Mut are later milestones.

### Statements

| Python AST form | v0.1 contract |
|---|---|
| return | Supported; every reachable value-returning path must return the declared type. |
| name = expression | Supported for local name targets. First binding lowers to let; later writes cause mutability analysis. |
| annotated local | Supported when the annotation is a supported Rust type. |
| augmented assignment | Supported for numeric locals after ordinary assignment semantics are stable. |
| if / else | Supported. Conditions must be rust.bool; Python truthiness is not applied. |
| while | Supported with a rust.bool condition. break and continue are added with loop tests. |
| for name in range(...) | Supported for statically typed integer ranges. |
| for name in rust.Vec | Deferred until iterator ownership and borrowing are explicit. |
| expression statement | Supported only for a call whose result is unit or intentionally discarded. |
| pass | Supported as a no-op. |
| assert | Deferred; it requires an explicit panic/error contract. |
| match | Deferred to the enum milestone. |
| try, raise, with | Deferred. |
| import inside rust.fn | Rejected; imports remain module-level declarations. |
| class, async, yield, global, nonlocal, delete | Rejected. |

### Expressions

| Python AST form | v0.1 contract |
|---|---|
| Integer, float, bool, string, None literals | Contextually typed. None is Option::None in an Option context and unit only where unit is expected. |
| Names | Resolve to locals, parameters, rust.fn symbols, declared Rust symbols, or an explicitly classified Python symbol. |
| +, -, *, /, % | Supported when the Rust operand types implement the operation. Division follows Rust typed division, not Python’s always-floating rule. |
| //, **, matrix multiplication | Deferred until their semantic mapping is explicitly decided. |
| Unary +, -, not | Supported for compatible numeric/bool types. Bitwise inversion is deferred. |
| ==, !=, <, <=, >, >= | Supported for compatible Rust types. Chained comparisons are deferred so evaluation-once behavior is not accidentally changed. |
| and, or | Supported only for bool operands and produce bool. Python’s operand-returning truthiness semantics do not apply. |
| Function call | Local rust.fn calls and an allowlisted set of constructors/functions are supported. |
| Method call | Supported only for methods in the versioned type capability table. rustc remains the final type authority. |
| Attribute path | Supported for statically resolved Rust modules/types and explicitly classified Python symbols. Dynamic getattr behavior is rejected. |
| Indexing | Vec indexing is added only with bounds/panic behavior documented. Slicing is deferred. |
| List/dict/set/tuple literals | Rejected as Python containers. Explicit Rust constructors are required. A narrow tuple lowering may be added later. |
| Comprehensions and generator expressions | Deferred. |
| Conditional expression | Deferred until branch typing and source mapping are proven. |
| f-string | Deferred. |
| await, yield, named expression | Rejected. |

## Valid-Python correction: Option None spelling

The architecture brief illustrates rust.None. That spelling is not valid Python grammar because None is a keyword. The recommended contract is:

    @rust.fn
    def divide(x: rust.f64, y: rust.f64) -> rust.Option[rust.f64]:
        if y == 0.0:
            return None
        return rust.Some(x / y)

The expected Option type gives None its Rust meaning. If an explicit constructor is later needed, rust.none() or rust.None_ can be considered through an ADR; rust.None cannot be part of a valid-Python API.

## Semantic rules

### Rust semantics are intentional

Inside rust.fn, explicit Rust types select Rust semantics. Crabwalk must document differences instead of trying to make Rust imitate all Python behavior.

| Topic | Provisional rule |
|---|---|
| Truthiness | Only rust.bool is valid as a condition. Containers, integers, Python objects, and Option do not receive Python truthiness. |
| Integer input | Python integers are range-checked at the boundary. No truncation or wrap is allowed during conversion. |
| Integer arithmetic | Enable overflow checks in development and release for early versions so behavior does not depend on build profile. Revisit only with an explicit policy. |
| Division | Uses Rust’s operator for the operand types. Integer division therefore differs from Python /. Python // is initially unsupported. |
| Name scope | Definite assignment is required. Branch/loop lowering may introduce outer Rust bindings, but reading a maybe-uninitialized name is rejected. |
| Moves and copies | Rust rules apply. Copy types may be reused; owned non-Copy values move unless borrowed or cloned explicitly. |
| Evaluation order | Preserve source evaluation order for supported expressions when calls or boundaries make it observable, introducing temporaries as needed. |
| Exceptions | Python exception syntax is unavailable inside the core Rust subset. Result and Option are the native mechanisms. |
| Panics | Generated operations that can panic must be documented. A panic may never unwind across the Python ABI. |
| Recursion | Calls between generated Rust functions stay native. |
| Globals | Only statically supported constants, crates, modules, and functions are visible; arbitrary mutable Python global access is a boundary or an error. |

### Local type inference

- Public rust.fn signatures are explicit.
- Literal and local types may be inferred when the result is unambiguous and rustc can validate it.
- Crabwalk’s IR records resolved declared types and constraints; it does not attempt to reimplement the full Rust type checker.
- When inference failure originates in generated Rust, the diagnostic mapper must identify the originating Python expression and retain the rustc detail.

### Mutability

Python has assignment but no let mut syntax. Crabwalk performs a local write analysis:

1. A name written exactly once lowers to an immutable Rust binding.
2. A name written again lowers to a mutable binding if doing so preserves control-flow semantics.
3. Rebinding a value with an incompatible type is rejected.
4. Mutation through a value is distinct from rebinding its name and follows the Rust type’s method/borrow rules.
5. Generated mut is inspectable; an inspection diagnostic may explain why it was required.

## v0.1 standard-type capability table

This is deliberately smaller than each Rust type’s full API.

| Type | Initial operations |
|---|---|
| Numeric primitives | Literal construction, arithmetic listed above, comparisons, explicit casts through a checked Crabwalk API |
| bool | Literals, comparisons, and/or/not |
| String | Construct from supported string input, len, is_empty, equality, borrow as Str |
| Str | len, is_empty, equality; argument/local use only |
| Vec[T] | new, with_capacity, push, pop as Option, len, is_empty; indexing only after bounds policy is accepted |
| Option[T] | None, rust.Some(value), is_some, is_none, unwrap_or; unrestricted unwrap is deferred or explicitly warned |
| Result[T, E] | rust.Ok(value), rust.Err(error), is_ok, is_err, basic propagation only after valid-Python syntax is chosen |

Every additional method is a product-surface addition even if Rust already supplies it. Crabwalk may mechanically emit a method path and let rustc check it only after the resolver can classify the receiver and produce a useful source-mapped failure.

## Boundary and conversion contract

Every operation is classified as one of:

- Native Rust
- Conversion boundary
- Python runtime boundary
- Unsupported

The classification is stored in IR and exposed by inspect tooling.

### Primitive conversion policy

| Direction | Behavior |
|---|---|
| Python int → Rust integer | Exact range check; TypeError for non-int/bool mismatch and OverflowError for out-of-range input |
| Rust integer → Python int | Exact conversion |
| Python float/int → Rust float | Explicitly documented precision behavior; reject values the chosen PyO3 conversion cannot represent as contracted |
| Rust float → Python float | Normal Python float conversion |
| Python bool ↔ Rust bool | Exact bool only on input |
| Python str → Rust String | UTF-8 copy/allocation, marked as a conversion boundary |
| Python str → Rust Str | Borrow for the duration of the native call only when the ABI implementation proves the lifetime; never retained |
| Rust String → Python str | Allocation/conversion, marked as a boundary |
| Python sequence → Vec[T] | Explicit conversion helper in v0.1; element-indexed errors |
| Vec[T] → Python list | Explicit conversion helper in v0.1; Rust-owned wrappers arrive in M5 |
| Python None ↔ Option::None | Automatic where T conversion is defined |
| Option::Some(T) ↔ Python value | Uses T conversion |

Implicit conversions should be limited to primitive exported parameters/returns. Potentially expensive container conversion must be explicit and visible.

### First Python runtime boundary

M3 initially supports the built-in print call with ABI-convertible arguments:

    @rust.fn
    def hello() -> None:
        print("hello from Python")
        rust.println("hello from Rust")

The first call is marked Python runtime boundary; the second is Native Rust. General third-party Python calls are not declared v0.1 support merely because their syntax can be parsed. They require a typed result/exception/import policy and are promoted in later slices.

### Result at an exported boundary

Provisional policy:

- Result remains a real Rust Result inside generated Rust.
- Ok(value) converts according to the exported return contract.
- Err(error) becomes a CrabwalkRustError containing a stable error type label and safe display text until typed exception mappings exist.
- No implicit panic or silent defaulting is allowed.
- A future API may expose a Rust-backed Result object, but v0.1 does not need both models.

## Unsupported and rejected behavior

The following are outside v0.1 even when valid Python syntax:

- Dynamic imports, eval, exec, locals, globals, and reflection
- Monkey-patching or reassignment of Rust symbols
- Arbitrary Python object attributes in native expressions
- Closures, decorators other than rust.fn, generators, coroutines, and context managers
- Python containers standing in for Rust containers
- Implicit conversion of complex object graphs
- User-defined operators
- Exceptions as Rust control flow
- Unsafe Rust authoring
- Traits, impl blocks, lifetime parameters, and higher-ranked types
- Macro calls
- Arbitrary crate API discovery
- Structs and enums before M6
- Threads, Rayon, Tokio, and Python event-loop interoperation

Rejection is part of the product. Each category needs a stable diagnostic code, a source span, and at least one actionable alternative.

## User-facing commands by v0.1

| Command | Contract |
|---|---|
| crabwalk doctor | Report Python, Crabwalk, rustc, Cargo, target, linker, and extension-build readiness without mutating the project. |
| crabwalk check PATH | Parse, resolve, validate, generate, and run Cargo check without installing/loading an extension. |
| crabwalk build PATH | Produce the content-addressed native artifact and metadata. |
| crabwalk expand PATH | Materialize deterministic generated Rust, Cargo inputs, and source-map metadata for inspection. |
| crabwalk show FILE:SYMBOL | Show the generated Rust associated with one Python symbol plus boundary annotations. |
| crabwalk inspect PATH | Classify native operations, conversions, Python calls, unsupported forms, and cache inputs. |

Import-time compilation uses the same pipeline and cache as these commands; it is not a second compiler path.

## Diagnostic contract

Every Crabwalk diagnostic contains:

- Stable CRAB code
- Severity
- Short title
- Primary original-Python span
- Plain-language explanation
- At least one actionable next step when possible
- Related spans for earlier definitions, moves, or borrows
- Underlying rustc code and rendered detail when rustc produced the error
- Generated file/span only as expandable secondary detail

Initial families:

| Range | Category |
|---|---|
| CRAB0xx | Environment, configuration, and project discovery |
| CRAB1xx | Syntax subset, symbols, types, and lowering |
| CRAB2xx | Python runtime and conversion boundaries |
| CRAB3xx | Cargo, cache, and artifact build |
| CRAB4xx | Extension loading and ABI |
| CRAB5xx | Ownership state exposed to Python |

## Feature promotion rule

A feature moves from Deferred to Supported only when all are present:

1. Written source syntax and semantic rule.
2. IR representation with source spans and boundary effects.
3. Valid lowering that emits real Rust.
4. Positive runtime or compile fixture.
5. Negative and misuse fixtures.
6. Source-mapped diagnostic behavior.
7. Cache fingerprint coverage if the feature changes build inputs.
8. User documentation and generated-code example.
9. Cross-platform evidence appropriate to its ABI/build risk.

## v0.1 definition of done

v0.1 is ready for an alpha tag when:

- M1, M2, and M3 exit gates in [[Crabwalk Roadmap]] pass.
- The active source subset matches this note and has no silent acceptance gaps.
- A clean machine can run doctor, build the examples, and observe a cache hit.
- The supported platform matrix in [[Crabwalk Verification and Release]] passes.
- All primary diagnostics reference Python source.
- The package can be installed in a clean environment using the documented Python packaging path.
- Generated source, source maps, fingerprints, and dependency/build commands are inspectable.
- Known limitations include semantic differences, toolchain requirements, build-script trust, and unsupported syntax.

