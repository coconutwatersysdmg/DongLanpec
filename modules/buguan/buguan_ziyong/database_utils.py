import pymysql

def create_connection():
    """创建数据库连接"""
    try:
        connection = pymysql.connect(
            host='localhost',
            port=3306,
            database='产品设计活动库',
            user='root',
            password='123456',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

        return connection
    except pymysql.MySQLError as e:
        print(f"连接数据库时出错: {e}")
        return None

def execute_query(connection, query):
    """执行SQL查询"""
    cursor = connection.cursor()
    try:
        cursor.execute(query)
        connection.commit()
        return True
    except pymysql.MySQLError as e:
        print(f"执行查询时出错: {e}")
        return

    """创建数据库连接"""
    try:
        connection = pymysql.connect(
            host='localhost',
            database='元件库',
            user='root',
            password='123456',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        return connection
    except pymysql.MySQLError as e:
        print(f"连接数据库时出错: {e}")
        return None

def execute_query(connection, query):
    """执行SQL查询"""
    cursor = connection.cursor()
    try:
        cursor.execute(query)
        connection.commit()
        return True
    except pymysql.MySQLError as e:
        print(f"执行查询时出错: {e}")
        return False
