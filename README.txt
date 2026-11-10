How to test the FastAPI endpoints:
1. Run Docker Desktop (just to ensure the Docker daemon is running)
2. In a terminal window pointed at the root project directory, run: docker compose up --build
3. Type in any of these (or all) in the browser:
- http://localhost:8001/docs
- http://localhost:8002/docs
- http://localhost:8003/docs

4. To manually test the endpoints, click the dropdowns to expand the endpoint and click "Try It Out" to enter test values. Click execute to test.

5. Alternatively, install pytest (pip install pytest httpx) and run 'python -m pytest -v' in a separate terminal window pointed at the project root.
- This will automatically test the endpoints.

6. To simulate a crash, run a stop or kill command targeting a node (there are 3 nodes).
- Ex: docker compose stop node2
- Ex: docker compose kill node2

7. To stop the cluster and reset the environment/database, run: docker compose down -v