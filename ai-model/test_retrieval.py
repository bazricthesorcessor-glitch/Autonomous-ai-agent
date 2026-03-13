import json
import time
import memory_engine

def run_tests():
    try:
        with open("memory/test_set.json", "r") as f:
            test_cases = json.load(f)
    except FileNotFoundError:
        print("Error: memory/test_set.json not found.")
        return

    hits = 0
    top_1_hits = 0
    total = len(test_cases)
    total_latency = 0
    k = 3

    print(f"--- Starting Strict Benchmark (Top-{k}) ---\n")

    for i, case in enumerate(test_cases):
        query = case['query']
        target = case['expected_keyword'].lower()

        # Start Timer
        start_time = time.time()
        results = memory_engine.search_memory(query, top_k=k)
        end_time = time.time()

        latency_ms = (end_time - start_time) * 1000
        total_latency += latency_ms

        # Evaluate Rank
        found_rank = -1
        for rank, chunk in enumerate(results):
            if target in chunk.lower():
                found_rank = rank + 1
                break

        # Scoring
        if found_rank != -1:
            hits += 1
            status = "✅ PASS"
            if found_rank == 1:
                top_1_hits += 1
                status += " (Top-1 🎯)"
            else:
                status += f" (Rank #{found_rank})"
        else:
            status = "❌ FAIL"

        print(f"Test {i+1}: {status}")
        print(f"   Query: '{query}'")
        print(f"   Latency: {latency_ms:.2f}ms")
        if found_rank == -1 and results:
             print(f"   Top Result Preview: {results[0][:100]}...")
        print("")

    avg_latency = total_latency / total if total > 0 else 0

    print("-----------------------------------------")
    print(f"Final Report:")
    print(f"Recall@3: {hits}/{total} ({(hits/total)*100:.1f}%)")
    print(f"Top-1 Accuracy: {top_1_hits}/{total} ({(top_1_hits/total)*100:.1f}%)")
    print(f"Avg Latency: {avg_latency:.2f}ms")
    print("-----------------------------------------")

    # Integration Gate Check
    if (hits/total) >= 0.8 and (top_1_hits/total) >= 0.6 and avg_latency < 400:
        print("\n🚀 STATUS: READY FOR INTEGRATION.")
    else:
        print("\n⚠️ STATUS: NEEDS TUNING. Do NOT integrate yet.")

if __name__ == "__main__":
    run_tests()
