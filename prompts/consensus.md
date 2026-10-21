Consensus rules (implemented in code, kept here for reference):
1. Every finding needs a concrete file and line range that touches changed code.
2. Repeated findings are merged, not counted as votes.
3. Severity comes from impact and exploitability, never from vote counts.
4. A finding from one specialist is kept if its evidence is verified.
5. Disputed critical or high findings are marked unresolved, not deleted.
6. Performance claims without proof are labelled hypotheses and shown as optional.
7. Agents never modify the repository.
8. "No actionable findings" is a valid result.
