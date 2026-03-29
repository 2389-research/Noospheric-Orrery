---
notion-id: 23b75a11-a662-80f2-8fad-d5fbd239ce81
base: "[[Meeting Notes.base]]"
Attendees:
  - dylan richard
  - Michael Sugimura
  - Angelo Zangari
Created by: [[Harper Reed|Harper]] Reed
Created time: 2025-07-25T11:58:00
Event time: 2025-07-25
Type: Training
Last edited by: Harper Reed
Last edited time: 2025-07-25T11:58:00
---
# Fri, 25 Jul 25

### **Experimental Results & Model Performance**

- Sonnet 3.5 pipeline showing promising cost efficiency
    - Journal tool: ~10 cents per question vs baseline 26-27 cents (Sonnet 4)
    - Completing same code challenges at roughly half the cost
    - Social media tool performing comparably to engineered journal approach
- Baseline model (no tools) frequently spirals on hard problems
    - Burns $1-8 per question when struggling
    - One run still incomplete after getting stuck on bowling question
- Tool usage patterns observed
    - Models call read function ~10 times across 60 code challenges
    - Typically triggered when debugging frustration occurs
    - Searches journal for previous similar work to shortcut problems

### **Pipeline Development Status**

- First layer (data generation): 90% complete
    - Config YAML file for settings management
    - Docker containerization functional
    - Missing final prompt content integration
- Second layer (analysis): 20% complete
    - Python notebook extracts token usage, pricing data
    - Currently cobbled together but functional
    - Needs systematization for consistent output
- Third layer (interpretation): Not yet developed
    - Manual analysis of results and narrative building
    - Will determine paper conclusions

### **Experimental Methodology & Goals**

- Three-pronged evaluation framework needed
    - Cost/token efficiency metrics
    - Task completion quality assessment
    - User experience/“friendliness” scoring
- Hypothesis: Memory tools help models punch above weight class
    - Writing to journal/social media improves performance beyond just reading
    - Leverages training data patterns in unexpected ways
    - May work across different model architectures

### **Timeline & Deliverables**

- Target: Four solid experimental runs by early next week
- Paper writing to begin immediately after data collection
- Critical deadline: Complete before team member departure
- Harper presenting narrative Monday/Tuesday Japan time
- Need systematic, reproducible runner before scaling experiments

### **Next Steps**

- Complete pipeline runner implementation (Angelo)
- Finalize prompt content integration
- Execute tiered list of experimental runs (Sugi)
- Systematize analysis notebook for consistent data output
- Begin paper draft once experimental data collected