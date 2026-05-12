---
title: "Query Optimization at Petabyte Scale with Amazon Athena"
date: 2024-07-05
tags: ["aws", "athena", "data-engineering", "sql", "performance", "parquet"]
description: "Five techniques to make Athena queries 10-100x faster and 97% cheaper: file format, partitioning, bucketing, AWS Glue ETL, and query structure. With real percentage improvements and working DDL."
---

Amazon Athena charges you per byte scanned: $5 per terabyte. At petabyte scale, unoptimized queries cost tens of thousands of dollars per month. But cost is actually the lagging indicator — query runtime is what you feel day-to-day. A poorly structured query against unpartitioned CSV data can take 45 minutes and scan your entire dataset. The same query against partitioned Parquet runs in 3 minutes and scans 1% of the data.

This post covers the five techniques that matter most, with real numbers and working code.

## 1. File Format: Move to Parquet

The single highest-leverage change is switching from CSV or JSON to **Apache Parquet**.

Parquet is a columnar storage format. CSV and JSON are row-based. The difference matters enormously for analytics queries that select a subset of columns:

```sql
-- This query selects 3 columns from a 40-column table
SELECT user_id, amount, transaction_date
FROM transactions
WHERE transaction_date >= '2024-01-01'
```

With CSV/JSON: Athena reads every column for every row, then discards 37 columns.  
With Parquet: Athena reads *only* the 3 columns it needs, skipping the 37 entirely.

**Real improvement numbers** from migrating a production dataset:
- Query cost: reduced by **~77%**
- Query runtime: reduced by **~77%**

That's not a coincidence — less data scanned = less time + less money, roughly proportionally.

### Parquet Characteristics

Parquet stores data in row groups (default 128 MB each). Within each row group, each column is stored contiguously. It also maintains column statistics (min, max, null count) per row group, enabling **predicate pushdown** — Athena can skip entire row groups where the statistics prove the filter can't match.

**Compression**: Parquet supports several codecs. For Athena:
- **Snappy**: Best for read-heavy workloads. Fast decompression, moderate compression ratio (~3-4x).
- **GZIP**: Better compression ratio (~5-8x), slower decompression. Good if storage cost matters more than query speed.
- **ZSTD**: Best of both worlds — better compression than Snappy, faster than GZIP. Available in newer Parquet/Spark versions.

Use Snappy for interactive queries, ZSTD if you're writing a lot and want to optimize storage cost without sacrificing read speed.

### Creating a Parquet Table

```sql
CREATE EXTERNAL TABLE transactions_parquet (
  transaction_id STRING,
  user_id        STRING,
  amount         DOUBLE,
  currency       STRING,
  merchant       STRING,
  transaction_date DATE,
  status         STRING
)
STORED AS PARQUET
LOCATION 's3://your-bucket/transactions-parquet/'
TBLPROPERTIES (
  'parquet.compression' = 'SNAPPY'
);
```

## 2. Partitioning: Skip 99% of Data

Partitioning organizes your S3 data into prefix hierarchies that Athena can skip entirely based on query predicates.

Without partitioning:
```
s3://bucket/transactions/part-00001.parquet
s3://bucket/transactions/part-00002.parquet
... (thousands of files)
```

A query with `WHERE year = 2024 AND month = 3` still scans all files.

With partitioning:
```
s3://bucket/transactions/year=2024/month=3/part-00001.parquet
s3://bucket/transactions/year=2024/month=3/part-00002.parquet
s3://bucket/transactions/year=2023/month=12/part-00001.parquet
... 
```

The same query skips every partition except `year=2024/month=3`. If you have 3 years of data and query one month, you skip 97% of it.

**Real improvement numbers**:
- Query cost: reduced by **~99%** for time-range queries
- Query runtime: reduced by **~99%** for time-range queries

The 99% figure is real when your partition key matches your most common filter column.

### Partitioned Table DDL

```sql
CREATE EXTERNAL TABLE transactions_partitioned (
  transaction_id STRING,
  user_id        STRING,
  amount         DOUBLE,
  currency       STRING,
  merchant       STRING,
  status         STRING
)
PARTITIONED BY (
  year  INT,
  month INT,
  day   INT
)
STORED AS PARQUET
LOCATION 's3://your-bucket/transactions-partitioned/'
TBLPROPERTIES (
  'parquet.compression' = 'SNAPPY'
);
```

**Note**: The partition columns (`year`, `month`, `day`) are NOT in the main column list. Athena treats them as virtual columns that come from the S3 path.

### Loading Partitions

After writing data to the partitioned path structure, tell Athena about the partitions:

```sql
-- Load all partitions automatically (can be slow for many partitions)
MSCK REPAIR TABLE transactions_partitioned;

-- Or add specific partitions manually (faster for large tables)
ALTER TABLE transactions_partitioned
ADD PARTITION (year=2024, month=3, day=15)
LOCATION 's3://your-bucket/transactions-partitioned/year=2024/month=3/day=15/';
```

For automated partition addition as new data arrives, use **AWS Glue Crawlers** — they detect new partitions in S3 and update the Glue catalog automatically.

### Partition Granularity

Choosing the right partition granularity involves a tradeoff:

| Granularity | Partition count (3 years) | Advantage | Disadvantage |
|-------------|--------------------------|-----------|--------------|
| Year | 3 | Few partitions | Queries filter at most 66% of data |
| Month | 36 | Good balance | |
| Day | 1,095 | 99% filter rate | Many small files problem |
| Hour | 26,280 | Maximum skip | Extreme small files, slow metadata |

**The small files problem**: If daily data produces many tiny files (< 128 MB), Athena must open many files for each query, and overhead dominates. Aim for partitions containing 128 MB - 1 GB of data. If daily volumes are small, partition by month or week.

## 3. Bucketing: Within-Partition Optimization

Bucketing is partitioning's complement. Where partitioning organizes data by a high-cardinality column with low selectivity (date), bucketing organizes within a partition by a column with *high* selectivity for your queries (user_id, entity_id).

```sql
CREATE EXTERNAL TABLE transactions_bucketed (
  transaction_id STRING,
  user_id        STRING,
  amount         DOUBLE,
  currency       STRING,
  merchant       STRING,
  status         STRING
)
PARTITIONED BY (year INT, month INT)
CLUSTERED BY (user_id) INTO 256 BUCKETS
STORED AS PARQUET
LOCATION 's3://your-bucket/transactions-bucketed/'
TBLPROPERTIES (
  'parquet.compression' = 'SNAPPY'
);
```

With bucketing, `user_id` is hashed into 256 buckets. All data for a given user always lands in the same bucket. A query filtering on `user_id` can skip 255/256 buckets (99.6% of the partition).

**Real improvement numbers** for user-scoped queries:
- Query cost: reduced by **~97%**
- Query runtime: reduced by **~34%**

The asymmetry (97% cost reduction, 34% runtime reduction) is because Athena still opens all bucket files initially — the runtime savings come from reading much less data from each file, while cost is directly proportional to bytes scanned.

**Important**: Both tables in a JOIN must be bucketed on the join key with the same number of buckets for Athena to use a bucket-aware join that avoids shuffling all data.

## 4. AWS Glue ETL: Converting Existing Data

If you have data in S3 as CSV or JSON, use AWS Glue to convert it to Parquet with the right partition structure.

### Glue Job in Java (Spark)

```java
import com.amazonaws.services.glue.GlueContext;
import com.amazonaws.services.glue.DynamicFrame;
import com.amazonaws.services.glue.util.Job;
import org.apache.spark.SparkContext;

public class TransactionETL {
    
    public static void main(String[] args) {
        SparkContext sc = new SparkContext();
        GlueContext glueContext = new GlueContext(sc);
        Job.init("transaction-parquet-conversion", glueContext, args);
        
        // Read source data (CSV from S3)
        DynamicFrame sourceDf = glueContext.create_dynamic_frame_from_options(
            connection_type = "s3",
            connection_options = {
                "paths": ["s3://source-bucket/raw/transactions/"],
                "recurse": true
            },
            format = "csv",
            format_options = {
                "withHeader": true,
                "separator": ","
            }
        );
        
        // Add partition columns derived from timestamp
        DynamicFrame partitioned = sourceDf.applyMapping(
            mappings = new String[][]{
                {"transaction_id", "string", "transaction_id", "string"},
                {"user_id", "string", "user_id", "string"},
                {"amount", "string", "amount", "double"},
                {"transaction_date", "string", "transaction_date", "date"},
                // ... other mappings
            }
        );
        
        // Write as partitioned Parquet
        glueContext.write_dynamic_frame_from_options(
            frame = partitioned,
            connection_type = "s3",
            connection_options = {
                "path": "s3://output-bucket/transactions-parquet/",
                "partitionKeys": ["year", "month", "day"]
            },
            format = "parquet",
            format_options = {
                "compression": "snappy"
            }
        );
        
        Job.commit();
    }
}
```

### Adding Derived Partition Columns with Spark SQL

Before writing, derive the partition columns from existing date fields:

```java
// Using Spark SQL to add partition columns
Dataset<Row> df = glueContext.getSparkSession()
    .sql("SELECT *, " +
         "YEAR(transaction_date) AS year, " +
         "MONTH(transaction_date) AS month, " +
         "DAY(transaction_date) AS day " +
         "FROM source_table");

// Write with dynamic partitioning
df.write()
  .mode(SaveMode.Overwrite)
  .partitionBy("year", "month", "day")
  .parquet("s3://output-bucket/transactions-parquet/");
```

### Incremental ETL

For ongoing data, run incremental Glue jobs that process only new partitions:

```java
// Get yesterday's date for incremental processing
LocalDate yesterday = LocalDate.now().minusDays(1);
String sourcePath = String.format(
    "s3://source-bucket/raw/year=%d/month=%02d/day=%02d/",
    yesterday.getYear(),
    yesterday.getMonthValue(), 
    yesterday.getDayOfMonth()
);

// Process only yesterday's data
DynamicFrame dailyFrame = glueContext.create_dynamic_frame_from_options(
    connection_type = "s3",
    connection_options = {"paths": [sourcePath]},
    format = "parquet"
);
```

Schedule this with EventBridge (formerly CloudWatch Events) to run daily after your data pipeline writes the previous day's data.

## 5. Query Structure: Don't Undo Your Optimizations

Even with Parquet and partitioning, poorly written queries bypass your optimizations.

### Always Filter on Partition Columns

```sql
-- GOOD: Athena prunes partitions
SELECT user_id, SUM(amount)
FROM transactions
WHERE year = 2024 AND month = 3
GROUP BY user_id;

-- BAD: Forces full table scan
SELECT user_id, SUM(amount)  
FROM transactions
WHERE transaction_date BETWEEN '2024-03-01' AND '2024-03-31'
GROUP BY user_id;
```

The second query uses `transaction_date` (a non-partition column) for the filter. Athena can't use partition pruning — it must open every partition and read the data to check the filter. Always filter on the partition column explicitly.

### SELECT Only What You Need

```sql
-- GOOD: Reads only 3 columns from each row group
SELECT user_id, amount, status
FROM transactions
WHERE year = 2024 AND month = 3;

-- BAD: Reads all columns (no savings from columnar storage)
SELECT *
FROM transactions
WHERE year = 2024 AND month = 3;
```

`SELECT *` reads all columns. Parquet is columnar — you only pay for what you select. Be specific.

### Avoid Functions on Partition Columns

```sql
-- GOOD: Direct comparison, Athena can prune
WHERE year = 2024 AND month = 3

-- BAD: Function prevents partition pruning
WHERE DATE_FORMAT(transaction_date, '%Y-%m') = '2024-03'
```

Applying a function to a partition column prevents Athena from pruning. The optimizer can't determine which partitions match without reading all of them.

### APPROXIMATE_COUNT_DISTINCT for Large Cardinality Estimates

```sql
-- Exact count — scans everything
SELECT COUNT(DISTINCT user_id) FROM transactions WHERE year = 2024;

-- Approximate count — 2-3% error margin, 10x faster
SELECT APPROX_DISTINCT(user_id) FROM transactions WHERE year = 2024;
```

If you need an approximate answer (e.g., for dashboards), `APPROX_DISTINCT` uses HyperLogLog and can be dramatically faster on large datasets.

### CTE vs Subquery Performance

Athena (Presto/Trino-based) executes CTEs as materialized subqueries. For complex queries:

```sql
-- CTEs materialize intermediate results — good for reuse
WITH monthly_totals AS (
    SELECT user_id, 
           year, month,
           SUM(amount) AS total
    FROM transactions
    WHERE year = 2024
    GROUP BY user_id, year, month
),
high_spenders AS (
    SELECT user_id
    FROM monthly_totals
    WHERE total > 10000
)
SELECT t.*
FROM transactions t
JOIN high_spenders h ON t.user_id = h.user_id
WHERE t.year = 2024 AND t.month = 3;
```

## Monitoring and Cost Control

### Query Execution Statistics

After every query, Athena reports data scanned in the console and API. Log these to CloudWatch:

```python
import boto3

athena = boto3.client('athena')

response = athena.get_query_execution(
    QueryExecutionId=query_execution_id
)

statistics = response['QueryExecution']['Statistics']
data_scanned_mb = statistics['DataScannedInBytes'] / (1024 * 1024)
runtime_seconds = statistics['TotalExecutionTimeInMillis'] / 1000

print(f"Data scanned: {data_scanned_mb:.1f} MB")
print(f"Runtime: {runtime_seconds:.1f}s")
print(f"Estimated cost: ${data_scanned_mb / 1024 / 1024 * 5:.4f}")
```

### Workgroup Query Limits

Set workgroup limits to prevent runaway queries:

```hcl
resource "aws_athena_workgroup" "main" {
  name = "production"

  configuration {
    result_configuration {
      output_location = "s3://athena-results/production/"
    }
    
    bytes_scanned_cutoff_per_query = 10737418240  # 10 GB limit
    
    engine_version {
      selected_engine_version = "Athena engine version 3"
    }
  }
}
```

Queries that would scan more than 10 GB are cancelled automatically. Adjust based on your workload — a reasonable limit prevents a forgotten `SELECT *` with no partition filter from costing thousands of dollars.

## Summary: The Optimization Stack

Apply these in order of impact:

| Technique | Cost reduction | Runtime reduction | Effort |
|-----------|---------------|-------------------|--------|
| Parquet + Snappy | ~77% | ~77% | Medium (one-time ETL) |
| Partitioning by date | ~99% for time queries | ~99% for time queries | Medium |
| Bucketing by entity | ~97% for entity queries | ~34% for entity queries | Medium |
| Query structure | Varies | Varies | Low (code review) |
| Compression (ZSTD) | ~10% additional | Minimal | Low (config change) |

For most teams, the first two changes (Parquet + partitioning) deliver 95% of the possible savings. Bucketing is worth adding if you have heavy per-entity query patterns. Query structure discipline is table stakes — teach it in code review.

The investment is a one-time Glue ETL job to convert historical data and updated ingestion pipelines going forward. At petabyte scale, the savings pay for the engineering time many times over in the first month.
