---
notion-id: 22c75a11-a662-8080-b2a6-c6f23d40a670
base: "[[Meeting Notes.base]]"
Created by: Sophie Davis
Created time: 2025-07-10T12:34:00
Last edited by: Sophie Davis
Last edited time: 2025-07-10T12:34:00
---
### Project Demo Overview

- Avatar implementation in Godot engine with drag functionality
- Mouse interaction features:
    - Click and drag capability
    - Hover detection
    - Right-click to exit
- Chat functionality placeholder with planned LLM integration
- Window constraints prevent avatar from moving beyond screen bounds

### Technical Architecture

- Main entry point structure with node system
    - Scenes and scripts attached to nodes
    - Game manager instances prevent overlap
    - Memory leak prevention through proper instance management
- Integration with Cloud Code/Claude
    - System uses CloudMD for configuration
    - Specific hardware/Godot version requirements documented
    - References Godot documentation for accurate function calls

### Development Process

- Uses ChatGPT for initial concept development
- Workflow:
    - Feed general project requirements
    - Generate specific prompts for Cloud
    - Implement in Godot with system-specific considerations
- Current focus on narrow, specific tasks for better results
- Documentation integration improving with correct version matching

### Cross-Platform Considerations

- Export presets available for different platforms:
    - Windows desktop (current focus)
    - Linux
    - Mobile
    - MacOS (planned)
- Compatibility options:
    - Current configuration
    - Forward Plus version available for cross-platform development
- System-specific configurations required for optimal rendering

### Next Steps

- Implement Sprite Sheets received from [[Harper Reed|Harper]]
- Add testing implementation in CI pipeline
- Continue refining CloudMD configuration
- Explore cross-platform testing, particularly for MacOS
- Follow best practices for testing and development implementation