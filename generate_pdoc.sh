echo "generate pydoc for ABB classes..."
# "./k9_aif_abb" (not "k9_aif_abb") forces pdoc to document the LOCAL source
# tree. Without the "./" prefix, pdoc prefers an installed same-named package
# on sys.path — if k9-aif is pip-installed in this venv (even just for
# dependency resolution, not editable), it silently documents that installed
# version instead of your local edits, which is stale the moment local code
# diverges from whatever version is installed.
pdoc -o docs/pydocs ./k9_aif_abb
echo "Done! generating pydoc for ABB classes..."
echo "Ready to Rumble!"
echo " "
