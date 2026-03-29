---
notion-id: 17375a11-a662-8022-a5c5-f3df65ec1871
base: "[[Meeting Notes.base]]"
Attendees:
  - dylan richard
  - [[Harper Reed|Harper]] Reed
  - a556b943-3062-4019-8a5a-f62b577e69e0
  - [[Clint Ecker|Clint]] Ecker
  - Ivan Indrautama
Created by: Harper Reed
Created time: 2025-01-06T15:49:00
Type: Brainstorm
Last edited by: Harper Reed
Last edited time: 2025-01-10T11:52:00
---

Meeting Summary:
This was a technical discussion about building a multi-agent AI platform where different specialized agents (called "elves" in the discussion) work together to accomplish tasks. The system would allow both AI agents and human experts to collaborate in a chat-like interface, with the ability to maintain knowledge graphs of expertise and relationships.

Key Concepts Discussed:

1. Multi-agent framework with discrete agents/bots having specific expertise areas
2. Knowledge graph system to track expertise and relationships
3. Manager bot concept to coordinate between agents
4. Integration of human experts into the system
5. Lore/personality aspects to make interactions more engaging
6. Asynchronous task handling capability

Technical Takeaways:

7. Initial implementation will use Python
8. Planning to use Discord or Slack for proof of concept
9. Need for robust testing infrastructure
10. Langchain identified as current leading framework
11. Need to standardize API interfaces between components

Action Items:

12. Set up permissions:
    - Harper to set up Discord permissions for team members
    - Harper to enable repo creation permissions on 23/89 for team members
13. Repository Work:
    - Clint to push existing Discord bot code to 23/89 repository
    - Team to standardize on Python for initial development
14. Legal/Administrative:
    - Need to work with lawyers to formally bring Suji onto the team
15. Development Process:
    - Implement twice-weekly meetings to review prompts and share best practices
    - Set up aggressive testing infrastructure
    - Use GitHub issues for tracking
    - Implement main branch protection with required passing tests

Proof of Concept Goals:

16. First POC: Multiple discrete agents interacting in separate paths
17. Second POC: Knowledge base integration and RAG implementation
18. Third POC: Discrete agents with specific useful tasks

Business/Funding:

- Harper planning New York trip in early February to meet with Betaworks
- Working on white paper
- Targeting initial funding of a few million dollars
- Focus on keeping team small and building proof of concepts

Follow-up Items:

19. Need to determine specific interface approach (Discord vs Slack vs custom web)
20. Need to establish framework for agent management
21. Define knowledge graph implementation strategy
22. Set up standardized documentation process
23. Establish workflow for asynchronous task handling

The team emphasized starting simple with proof of concepts rather than over-engineering initially, with a focus on getting people to actually use the system. The strategy is to differentiate through style and user experience rather than trying to compete directly with larger AI platforms.