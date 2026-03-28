---
notion-id: 15f75a11-a662-802c-93f2-c1ec7a6dc2e9
base: "[[Meeting Notes.base]]"
Attendees:
  - [[Harper Reed|Harper]] Reed
Created by: Harper Reed
Created time: 2024-12-17T14:22:00
Event time: 2024-12-13
Last edited by: Harper Reed
Last edited time: 2024-12-17T14:22:00
---
# **Harper & Nathan (and friends as desired)**

Fri, 13 Dec 24 · nathanstoll@gmail.com

### **Current Project Status & Technical Exploration**

- Built meme search engine (Meme.rodeo) to learn about CLIP models and vector databases
- Developed database of ~2.5M products with 600k processed images
- Implemented vector search combining text/image embeddings by averaging vectors
- Achieved “magical” semantic concept searching (e.g. searching “goth” shows relevant black items)
- Found data quality is a major challenge - requires synthesizing better product data

### **Product Development Approach**

- Moving away from procedural prompt running toward true multi-agent systems
- Exploring chat interface where users can watch agents work and interrupt
- Testing personalization by incorporating user context/preferences into vector space
- Need to make processes visible to users - “people want to see work happening”
- Implementing pass-through caches for knowledge bases to extract and store relevant information

### **Development Process Insights**

- Friend’s successful approach with 2 contractors and $1.5M:
    - Uses ChatGPT to scope features
    - Uses Claude to generate development prompts
    - Implements in GitHub workspace
    - Uses robust test-driven development
    - Either debugs or restarts if tests fail

### **Productivity & Time Management**

- “You can’t do anything well for more than 3 hours at a time”
- Need to structure day around 3-hour focused blocks
- Exploring concept of “slow productivity” vs hustle culture
- Balance between work and family time requires clear boundaries
- Discussion of stocking stuffer projects - manageable tasks for holiday periods

### **Market Opportunity Analysis**

- Look for approximately 10x value multipliers for customers
- Focus on “annoying harder” problems others avoid
- Example: Playsets
    - New from Costco with assembly: $10k
    - Used from Craigslist: $500 + installation/refinishing
- Interior designers as potential go-to-market strategy
    - Currently struggle with vendor management
    - Need better tools for purchase tracking and logistics

### **Human-AI Interaction Philosophy**

- Need to maintain human involvement rather than full automation
- Success of “humble” approaches that ask users for help
- Importance of making processes visible and interruptible
- Value of human expertise alongside AI capabilities

### **Team & Collaboration Insights**

- Discussion of working with co-founder [[Dylan Richard|Dylan]]’s motivation levels
- Challenge of building company while maintaining family life
- Value of having at least one partner with stable full-time job
- Importance of setting clear expectations around availability

### **Technical Architecture Decisions**

- Testing personalization within vector space using Instagram data
- Implementing pass-through caches for knowledge bases
- Exploring Rust vs Go for development speed
- Need for robust test coverage and efficient test suites
- Value of proper project management and code review processes

---

Chat with meeting transcript: [https://notes.granola.ai/p/f156e7cd-4941-48b4-80c7-5f24895c0798](https://notes.granola.ai/p/f156e7cd-4941-48b4-80c7-5f24895c0798)