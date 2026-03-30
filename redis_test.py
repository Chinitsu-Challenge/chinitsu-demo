import redis
from redis.exceptions import RedisError

HOST = "8.155.149.12"
PORT = 26379
DB = 0


def main():
    try:
        r = redis.Redis(
            host=HOST,
            port=PORT,
            db=DB,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )

        print("1. 测试连接...")
        print("PING ->", r.ping())

        key = "test:hello"
        value = "world"

        print("2. 写入数据...")
        r.set(key, value)
        print(f"SET {key} = {value}")

        print("3. 读取数据...")
        result = r.get(key)
        print(f"GET {key} -> {result}")

        print("4. 删除数据...")
        r.delete(key)
        print(f"DEL {key} -> OK")

        print("5. 再次读取...")
        result = r.get(key)
        print(f"GET {key} -> {result}")

        print("Redis 测试完成，服务正常。")

    except RedisError as e:
        print("Redis 连接或操作失败：", e)
    except Exception as e:
        print("程序运行失败：", e)


if __name__ == "__main__":
    main()