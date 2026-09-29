from agents.research_planner import create_research_plan


question = "Analyze the Indian smartphone market under ₹30,000."

plan = create_research_plan(question)

print("\nRESEARCH PLAN\n")
print(plan)