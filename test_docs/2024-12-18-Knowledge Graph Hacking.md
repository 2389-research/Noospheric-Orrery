---
notion-id: 16075a11-a662-80e2-9951-de19a641fb88
base: "[[Meeting Notes.base]]"
Attendees:
  - a556b943-3062-4019-8a5a-f62b577e69e0
  - dylan richard
Created by: [[Harper Reed|Harper]] Reed
Created time: 2024-12-18T14:24:00
Last edited by: a556b943-3062-4019-8a5a-f62b577e69e0
Last edited time: 2024-12-18T14:53:00
---
# **Knowledge graph knowledge**

Wed, 18 Dec 24 · detour1999@gmail.com, me@clintecker.com, michaelsugimura@gmail.com

### **Knowledge Graph Architecture Discussion**

- Need to solve entity extraction from arbitrary data inputs
- Two potential approaches discussed:
    - Structured data with predefined schemas (simpler but less flexible)
    - Arbitrary data ingestion with dynamic entity extraction (more complex but powerful)
- Core technical components:
    - Entity extraction layer (using spaCy locally or LLMs)
        - Entities and or Attribute labeling ex 
    - Graph database for storing entities and relationships
    - Query/search interface to retrieve relevant information
- Potential test dataset: Enron email corpus (~600MB, contains ~150 employees’ emails)

### **Multi-Agent Framework Design**

- Goal: Create seamless interactions between human users and AI agents
- Key features needed:
    - Generic Discord bot framework
    - Multiple bots in one channel
    - Thread extension capabilities
    - Bot-to-bot communication
    - Manager bot for coordination
- Human-in-the-loop integration:
    - Ability to tag human experts within conversations
    - Seamless handoff between AI and human agents
    - Knowledge capture from human expert interactions

### **Commerce Use Case Implementation**

- Focus on buying experience differentiation:
    - Discovery phase (more defensible, requires bespoke data)
    - Transaction execution (less defensible, could be built in a hackathon)
- Key differentiator: User experience/“mouthfeel” of buying
- Example scenario discussed:
    - Gift buying use case with expert knowledge sharing
    - Dynamic knowledge graph building from user interactions
    - Integration of human expertise into the system

### **Technical Implementation Details**

- Tools discussed:
    - NetworkX for knowledge graph implementation
    - [Granola.so](http://granola.so/) for call recording/transcription
    - Local GPU setup with 4090s available
    - Google Colab as potential collaboration platform
- Current challenges:
    - Entity extraction accuracy needs improvement
    - Graph visualization for health monitoring
    - Balancing LLM API calls vs local processing
    - Need for efficient knowledge graph traversal

### **Next Steps**

- Sugi to experiment with entity extraction
- [[Dylan Richard|Dylan]] working on personal website as test case
- Harper to provide access to Notion documentation
- Team to explore test datasets beyond Enron emails
- Consider using Colab for shared development
- Document progress in shared Notion workspace

---

Chat with meeting transcript: [https://notes.granola.ai/p/181a1bc1-1db7-426e-94fa-7cf09d0fa821](https://notes.granola.ai/p/181a1bc1-1db7-426e-94fa-7cf09d0fa821)