# BoxLite Agent Tool Architecture

This document describes the complete tool architecture for the BoxLite Agent.
**Read this before starting any task to understand your available capabilities.**

## Critical Rules

### 1. spawn_section_workers - ONE TIME ONLY! ⛔⛔⛔

**THIS IS THE MOST IMPORTANT RULE:**

`spawn_section_workers()` can only be called **ONCE** per source. The system will **BLOCK** any repeated calls.

**Why?**
- Workers write files in parallel
- Calling again would overwrite existing files
- Creates duplicate/conflicting content
- Wastes API resources

**What to do AFTER workers have run:**
| Situation | Solution |
|-----------|----------|
| Need to fix errors | Use `edit_file()` or `write_file()` directly |
| Need to check status | Use `diagnose_preview_state()` |
| Some workers failed | Use `retry_failed_sections()` |
| Need visual check | Use `take_screenshot()` |

**NEVER call `spawn_section_workers()` again!**

### 2. Error Handling - NON-NEGOTIABLE
- **You CANNOT complete a task if there are build errors**
- Always run `diagnose_preview_state()` or `get_build_errors()` to check for errors
- If errors exist, you MUST fix them before proceeding
- The system will block completion if errors are detected

### 3. Completion Checklist
Before declaring any task complete, verify ALL of these:
- [ ] `diagnose_preview_state()` shows NO build errors
- [ ] `take_screenshot()` returns an actual image (not "Screenshot not available")
- [ ] The preview renders correctly

---

## Tool Categories

### 1. File Operations

| Tool | Description | When to Use |
|------|-------------|-------------|
| `write_file(path, content)` | Write/create a file | Creating new files, overwriting existing |
| `read_file(path)` | Read file with line numbers | Before editing, understanding code |
| `edit_file(path, old_text, new_text)` | Search & replace in file | Small targeted edits |
| `delete_file(path)` | Delete file/directory | Removing unused files |
| `list_files(path)` | List directory contents | Exploring file structure |
| `get_project_structure()` | Get full project tree | Understanding project layout |
| `search_in_file(path, pattern)` | Search in a file | Finding specific code |
| `search_in_project(pattern)` | Search all files | Finding code across project |

### 2. Terminal / Commands

| Tool | Description | When to Use |
|------|-------------|-------------|
| `shell(command, background)` | Execute shell command | npm install, npm run dev, mkdir, etc. |
| `install_dependencies(packages)` | Install npm packages | Adding new dependencies |
| `get_terminal_output(lines)` | Get terminal output | Checking command results |

**Important Shell Commands:**
```bash
# Install packages
shell("npm install <package>")
shell("npm install -D <package>")  # dev dependency

# Reinstall dependencies (fixes many errors)
shell("rm -rf node_modules && npm install")
```

**Note**: Dev server is managed automatically. You don't need to start it manually.

### 3. Diagnostics - THE MOST IMPORTANT TOOLS

| Tool | Description | When to Use |
|------|-------------|-------------|
| `diagnose_preview_state()` | **COMPREHENSIVE DIAGNOSIS** | ALWAYS use this to check status |
| `get_build_errors(source)` | Get build errors | When diagnose shows errors |
| `get_state()` | Get sandbox state | Check overall status |
| `verify_changes()` | Verify recent changes | After file modifications |
| `get_preview_status()` | Check preview server | If preview not loading |
| `take_screenshot()` | Capture preview image | Verify visual appearance |

### 4. Website Cloning Tools

| Tool | Description | When to Use |
|------|-------------|-------------|
| `get_layout(source_id)` | Analyze page structure | First step in cloning |
| `spawn_section_workers(source_id)` | Parallel section building ⚠️ **ONE TIME ONLY** | After get_layout, ONCE per source |
| `retry_failed_sections()` | Retry only failed workers | When some workers failed |
| `get_worker_status()` | Check worker results | After spawn_section_workers |

---

## Error Detection System (Three Layers)

The `get_build_errors()` tool uses a 3-layer detection system:

### Layer 1: Terminal Detector
- Parses terminal output for errors
- Catches: Vite errors, ESBuild errors, NPM errors, syntax errors
- Source: `terminal`

### Layer 2: Browser Detector (Playwright)
- Detects errors from actual browser preview
- Catches: Vite overlay, React error boundaries, console errors
- Source: `browser`

### Layer 3: Static Analyzer
- Analyzes code without running it
- Catches: Import path errors, basic syntax issues
- Source: `static`

**Usage:**
```
get_build_errors()              # All three layers (recommended)
get_build_errors(source="terminal")  # Only terminal
get_build_errors(source="browser")   # Only browser
get_build_errors(source="static")    # Only static
```

---

## Common Errors & Fixes

### Module Not Found
```
Error: Cannot find module 'tailwindcss'
Fix: shell("npm install tailwindcss")
```

### ENOENT node_modules
```
Error: ENOENT: node_modules/...
Fix: shell("rm -rf node_modules && npm install")
     OR use reinstall_dependencies()
```

### Syntax Error in JSX
```
Error: Unterminated JSX contents
Fix: Check JSX tags - every <tag> needs </tag> or />
```

### Import Path Error
```
Error: Failed to resolve import './Component'
Fix: Check file exists, verify path is correct
```

### Port Already in Use
```
Error: Port 8080 is already in use
Fix: Kill existing process or use different port
```

---

## Recommended Workflow

### For Website Cloning:
```
1. get_layout(source_id)           # Analyze structure
2. spawn_section_workers(source_id) # Build sections in parallel ⚠️ ONCE ONLY!
3. Wait for workers to complete
4. diagnose_preview_state()        # Check for errors
5. IF errors: Use edit_file() or write_file() to fix  ← NOT spawn_section_workers again!
6. IF some workers failed: Use retry_failed_sections()
7. take_screenshot()               # Verify visual
8. Done!
```

**⚠️ IMPORTANT:** If user sends a follow-up message, DO NOT call spawn_section_workers again!
Use edit_file(), write_file(), or other tools to address their request.

### For Bug Fixing:
```
1. diagnose_preview_state()        # Identify errors
2. read_file(affected_file)        # Understand the issue
3. edit_file(...) or write_file(...) # Fix the issue
4. diagnose_preview_state()        # Verify fix
5. IF still errors: goto 2
6. take_screenshot()               # Verify visual
7. Done!
```

### For Adding Features:
```
1. get_project_structure()         # Understand codebase
2. Write necessary files
3. shell("npm install <deps>")     # If new dependencies
4. diagnose_preview_state()        # Check for errors
5. Fix any errors
6. take_screenshot()               # Verify visual
7. Done!
```

---

## Important Notes

1. **Always check errors before completing** - The system will block you if there are unfixed errors

2. **Use diagnose_preview_state() liberally** - It's comprehensive and fast

3. **Don't skip the screenshot** - Visual verification is crucial

4. **Read files before editing** - Always understand current state first

5. **Background processes** - Use `background=true` for long-running commands like dev server

6. **Error suggestions** - The error system provides fix suggestions - use them!
