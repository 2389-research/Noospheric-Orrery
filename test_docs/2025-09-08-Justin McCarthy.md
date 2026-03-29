---
notion-id: 26875a11-a662-80c0-80ec-d876a65dacc1
base: "[[Meeting Notes.base]]"
Created by: [[Harper Reed|Harper Reed]]
Created time: 2025-09-08T13:52:00
Last edited by: Harper Reed
Last edited time: 2025-09-08T14:05:00
---
# Mon, 08 Sept 25 · justin@strongdm.com

### **Meeting Context**

- Harper Reed (board member at Keeper Security) meets with Justin McCarthy (Co-Founder & CTO at strongDM)
- strongDM team friendly with Keeper Security - no conflicts
- Connected by James who saw Justin demonstrating agent collaboration

### **Current AI Development Approach at strongDM**

- Building identity access management agent product
- Committed to zero human-written code or code review
    - Agents act as coders, reviewers, red team
    - “Pour more tokens on it” philosophy
- Specification through end-to-end narrative stories
    - Wake up, ask agent, get approval, navigate organization
    - Include adversarial examples (Harper tries to cheat)
- External corpus with blind testing via binaries
    - Agents can’t decompile but can exercise tests
    - Observe fluency, naturalness, surprises

### **Agent Infrastructure & Testing**

- DTU simulation environment
    - Zillions of simulated users
    - Time manipulation (forward/rewind)
    - Fake Jira, Okta, Slack APIs
- Feedback loop integration
    - Real user feedback weighted more heavily
    - Screenshot analysis flows back to sprint planning
    - Slack reactions trigger next sprint decisions
- Sprint cycles equivalent to ~30 minutes human work
- Software factory proxy tracking 300 kilotokens usage

### **Technical Implementation Details**

- Vivisected Claude Code and Codex, rewrote with specific workflows
- One-to-one ratio: markdown lines to code lines
- Language agnostic approach
    - “Doesn’t matter if it’s Rust or Go, just tastes better”
    - Python prototyping → C++/Rust production
- Miniatures concept: difficult algorithms in Python first
- State machine SDLC using DOT notation
    - Natural language transition conditions
    - Different complexity levels as code matures
- Cedar formalism integration for authorization proofing

### **Hiring & Team Philosophy**

- Filter: “Show me hobby projects you couldn’t avoid building in last 2 months”
- Teams structured as coaches + executors
    - Senior people as coaches with stored knowledge
    - Others hitting continue, drafting responses
- Swift mobile app for development on phones
- Physical AI team co-located for reduced latency
- No religious conversions - only talk to “post-converted” people

---

Chat with meeting transcript: [https://notes.granola.ai/d/9c8b4a92-b77a-4fca-8c83-1ad5e6839810](https://notes.granola.ai/d/9c8b4a92-b77a-4fca-8c83-1ad5e6839810)