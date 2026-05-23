from __future__ import annotations

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory


PACKAGE_NAME = "rm.custom_client"


def _add_field(
    message: descriptor_pb2.DescriptorProto,
    name: str,
    number: int,
    field_type: int,
    *,
    label: int = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
) -> None:
    field = message.field.add()
    field.name = name
    field.number = number
    field.label = label
    field.type = field_type


def _build_message_class(file_name: str, message_name: str, builder) :
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = file_name
    file_proto.package = PACKAGE_NAME
    file_proto.syntax = "proto3"

    message = file_proto.message_type.add()
    message.name = message_name
    builder(message)

    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(file_proto.SerializeToString())
    descriptor = pool.FindMessageTypeByName(f"{PACKAGE_NAME}.{message_name}")
    return message_factory.GetMessageClass(descriptor)


def build_global_unit_status_class():
    def build(message: descriptor_pb2.DescriptorProto) -> None:
        _add_field(message, "base_health", 1, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
        _add_field(message, "base_status", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
        _add_field(message, "base_shield", 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
        _add_field(message, "outpost_health", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
        _add_field(message, "outpost_status", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
        _add_field(message, "enemy_base_health", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
        _add_field(message, "enemy_base_status", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
        _add_field(message, "enemy_base_shield", 8, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
        _add_field(message, "enemy_outpost_health", 9, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
        _add_field(message, "enemy_outpost_status", 10, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
        _add_field(
            message,
            "robot_health",
            11,
            descriptor_pb2.FieldDescriptorProto.TYPE_UINT32,
            label=descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED,
        )
        _add_field(
            message,
            "robot_bullets",
            12,
            descriptor_pb2.FieldDescriptorProto.TYPE_INT32,
            label=descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED,
        )
        _add_field(message, "total_damage_ally", 13, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
        _add_field(message, "total_damage_enemy", 14, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)

    return _build_message_class("global_unit_status.proto", "GlobalUnitStatus", build)


def build_custom_byte_block_class():
    def build(message: descriptor_pb2.DescriptorProto) -> None:
        _add_field(message, "data", 1, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)

    return _build_message_class("custom_byte_block.proto", "CustomByteBlock", build)


GlobalUnitStatus = build_global_unit_status_class()
CustomByteBlock = build_custom_byte_block_class()
