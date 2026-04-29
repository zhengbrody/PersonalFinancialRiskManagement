"""
mindmarket_core — pure-compute primitives for the MindMarket AI risk platform.

Lazy-loading package: each submodule has different transitive deps
(black_scholes only needs scipy; var needs pandas; data_prep needs pandas).
Lambda services pin only what they use, so we MUST NOT eagerly import all
submodules here — doing that would force every Lambda to install pandas,
ballooning images and breaking options-pricer (which deliberately omits
pandas to save 70 MB).

Consumers should import the specific submodule:
    from libs.mindmarket_core import black_scholes
    from libs.mindmarket_core import var

Package-level exports kept minimal on purpose. If you need a curated public
surface, use one of the explicit module imports above.
"""
