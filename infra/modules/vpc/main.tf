module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "cdo-vpc-${var.environment}"
  cidr = var.vpc_cidr

  azs             = ["ap-southeast-1a", "ap-southeast-1b", "ap-southeast-1c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
  }
}

# -------------------------------------------------------------------
# VPC Gateway Endpoints — S3 và DynamoDB
# Gateway Endpoint hoàn toàn MIỄN PHÍ (không tính theo giờ, không tính data).
# Traffic từ EKS nodes (private subnet) đến S3/DynamoDB đi thẳng qua
# backbone AWS thay vì qua NAT Gateway → giảm NAT data charge + tăng bandwidth.
# Áp dụng cho: audit S3 write, TF state S3 read/write, DynamoDB idempotency lock.
# -------------------------------------------------------------------

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.ap-southeast-1.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids

  tags = {
    Name        = "cdo-vpc-s3-gw-${var.environment}"
    Project     = "tf3-cdo-02"
    Environment = var.environment
  }
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.ap-southeast-1.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids

  tags = {
    Name        = "cdo-vpc-dynamodb-gw-${var.environment}"
    Project     = "tf3-cdo-02"
    Environment = var.environment
  }
}
