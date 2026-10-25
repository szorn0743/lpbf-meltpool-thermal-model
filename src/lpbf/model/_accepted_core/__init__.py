"""Package-native migration of the accepted frozen scalar numerical core.

Patch 20.2 keeps the root Patch 16.6 modules byte-identical as reference evidence
while supported execution imports these package-native counterparts. Numerical
bodies are unchanged; only local/import namespaces are rewritten where required.
"""
