"""5 News pipeline.

A batch pipeline that collects news Articles, collapses syndicated Wire Copy,
clusters Articles describing the same Event, ranks those Clusters by Consensus
Score, and summarizes the survivors into Briefings.

Two halves that share nothing but a directory of files: this package writes
JSON to ``data/briefings/``; the site under ``site/`` reads it. Neither imports
the other.
"""
