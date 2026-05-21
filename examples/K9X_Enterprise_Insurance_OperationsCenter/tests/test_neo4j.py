from neo4j import GraphDatabase
from dotenv import load_dotenv
import os

load_dotenv()

uri = os.getenv("NEO4J_URI")
username = os.getenv("NEO4J_USER")
password = os.getenv("NEO4J_PASSWORD")

try:
    driver = GraphDatabase.driver(
        uri,
        auth=(username, password)
    )

    driver.verify_connectivity()
    print("✓ Driver connected")

    with driver.session() as session:
        result = session.run(
            "RETURN 'Hello from K9-AIF EOC Neo4j!' AS greeting"
        )

        print(result.single()["greeting"])

except Exception as e:
    print(f"Error: {type(e).__name__}")
    print(f"Details: {str(e)}")

finally:
    if 'driver' in locals():
        driver.close()