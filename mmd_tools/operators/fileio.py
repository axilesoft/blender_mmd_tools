# Copyright 2014 MMD Tools authors
# This file is part of MMD Tools.

import logging
import os
import re
import time
import traceback

import bpy
from bpy.types import Operator, OperatorFileListElement
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .. import auto_scene_setup
from ..core.camera import MMDCamera
from ..core.lamp import MMDLamp
from ..core.model import FnModel, Model
from ..core.pmd import importer as pmd_importer
from ..core.pmx import exporter as pmx_exporter
from ..core.pmx import importer as pmx_importer
from ..core.vmd import exporter as vmd_exporter
from ..core.vmd import importer as vmd_importer
from ..core.vpd import exporter as vpd_exporter
from ..core.vpd import importer as vpd_importer
from ..translations import DictionaryEnum
from ..utils import makePmxBoneMap

LOG_LEVEL_ITEMS = [
    ("DEBUG", "4. DEBUG", "", 1),
    ("INFO", "3. INFO", "", 2),
    ("WARNING", "2. WARNING", "", 3),
    ("ERROR", "1. ERROR", "", 4),
]


def log_handler(log_level, filepath=None):
    if filepath is None:
        handler = logging.StreamHandler()
    else:
        handler = logging.FileHandler(filepath, mode="w", encoding="utf-8")
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)
    return handler


def _update_types(cls, prop):
    types = cls.types.copy()

    if "PHYSICS" in types:
        types.add("ARMATURE")
    if "DISPLAY" in types:
        types.add("ARMATURE")
    if "MORPHS" in types:
        types.add("ARMATURE")
        types.add("MESH")

    if types != cls.types:
        cls.types = types  # trigger update


class ImportPmx(Operator, ImportHelper):
    bl_idname = "mmd_tools.import_model"
    bl_label = "Import Model File (.pmd, .pmx)"
    bl_description = "Import model file(s) (.pmd, .pmx)"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    files: bpy.props.CollectionProperty(type=OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: bpy.props.StringProperty(maxlen=1024, subtype="FILE_PATH", options={"HIDDEN", "SKIP_SAVE"})

    filename_ext = ".pmx"
    filter_glob: bpy.props.StringProperty(default="*.pmx;*.pmd", options={"HIDDEN"})

    types: bpy.props.EnumProperty(
        name="Types",
        description="Select which parts will be imported",
        options={"ENUM_FLAG"},
        items=[
            ("MESH", "Mesh", "Mesh", 1),
            ("ARMATURE", "Armature", "Armature", 2),
            ("PHYSICS", "Physics", "Rigidbodies and joints (include Armature)", 4),
            ("DISPLAY", "Display", "Display frames (include Armature)", 8),
            ("MORPHS", "Morphs", "Morphs (include Armature and Mesh)", 16),
        ],
        default={
            "MESH",
            "ARMATURE",
            "PHYSICS",
            "DISPLAY",
            "MORPHS",
        },
        update=_update_types,
    )
    scale: bpy.props.FloatProperty(
        name="Scale",
        description="Scaling factor for importing the model",
        default=0.08,
    )
    clean_model: bpy.props.BoolProperty(
        name="Clean Model",
        description="Remove unused vertices and duplicated/invalid faces",
        default=True,
    )
    remove_doubles: bpy.props.BoolProperty(
        name="Remove Doubles",
        description="Merge duplicated vertices and faces",
        default=False,
    )
    fix_IK_links: bpy.props.BoolProperty(
        name="Fix IK Links",
        description="Fix IK links to be blender suitable",
        default=False,
    )
    ik_loop_factor: bpy.props.IntProperty(
        name="IK Loop Factor",
        description="Scaling factor of MMD IK loop",
        min=1,
        soft_max=10,
        max=100,
        default=5,
    )
    apply_bone_fixed_axis: bpy.props.BoolProperty(
        name="Apply Bone Fixed Axis",
        description="Apply bone's fixed axis to be blender suitable",
        default=False,
    )
    rename_bones: bpy.props.BoolProperty(
        name="Rename Bones - L / R Suffix",
        description="Use Blender naming conventions for Left / Right paired bones",
        default=True,
    )
    use_underscore: bpy.props.BoolProperty(
        name="Rename Bones - Use Underscore",
        description="Will not use dot, e.g. if renaming bones, will use _R instead of .R",
        default=False,
    )
    dictionary: bpy.props.EnumProperty(
        name="Rename Bones To English",
        items=DictionaryEnum.get_dictionary_items,
        description="Translate bone names from Japanese to English using selected dictionary",
    )
    use_mipmap: bpy.props.BoolProperty(
        name="use MIP maps for UV textures",
        description="Specify if mipmaps will be generated",
        default=True,
    )
    sph_blend_factor: bpy.props.FloatProperty(
        name="influence of .sph textures",
        description="The diffuse color factor of texture slot for .sph textures",
        default=1.0,
    )
    spa_blend_factor: bpy.props.FloatProperty(
        name="influence of .spa textures",
        description="The diffuse color factor of texture slot for .spa textures",
        default=1.0,
    )
    log_level: bpy.props.EnumProperty(
        name="Log level",
        description="Select log level",
        items=LOG_LEVEL_ITEMS,
        default="INFO",
    )
    save_log: bpy.props.BoolProperty(
        name="Create a log file",
        description="Create a log file",
        default=False,
    )

    def execute(self, context):
        try:
            self.__translator = DictionaryEnum.get_translator(self.dictionary)
            if self.directory:
                for f in self.files:
                    self.filepath = os.path.join(self.directory, f.name)
                    self._do_execute(context)
            elif self.filepath:
                self._do_execute(context)
        except Exception as e:
            err_msg = traceback.format_exc()
            self.report({"ERROR"}, err_msg)
        return {"FINISHED"}

    def _do_execute(self, context):
        logger = logging.getLogger()
        logger.setLevel(self.log_level)
        if self.save_log:
            handler = log_handler(self.log_level, filepath=self.filepath + ".mmd_tools.import.log")
            logger.addHandler(handler)
        try:
            importer_cls = pmx_importer.PMXImporter
            if re.search("\.pmd$", self.filepath, flags=re.I):
                importer_cls = pmd_importer.PMDImporter

            importer_cls().execute(
                filepath=self.filepath,
                types=self.types,
                scale=self.scale,
                clean_model=self.clean_model,
                remove_doubles=self.remove_doubles,
                fix_IK_links=self.fix_IK_links,
                ik_loop_factor=self.ik_loop_factor,
                apply_bone_fixed_axis=self.apply_bone_fixed_axis,
                rename_LR_bones=self.rename_bones,
                use_underscore=self.use_underscore,
                translator=self.__translator,
                use_mipmap=self.use_mipmap,
                sph_blend_factor=self.sph_blend_factor,
                spa_blend_factor=self.spa_blend_factor,
            )
            self.report({"INFO"}, 'Imported MMD model from "%s"' % self.filepath)
        except Exception as e:
            err_msg = traceback.format_exc()
            logging.error(err_msg)
            raise
        finally:
            if self.save_log:
                logger.removeHandler(handler)

        return {"FINISHED"}


class ImportVmd(Operator, ImportHelper):
    bl_idname = "mmd_tools.import_vmd"
    bl_label = "Import VMD File (.vmd)"
    bl_description = "Import a VMD file to selected objects (.vmd)"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    filename_ext = ".vmd"
    filter_glob: bpy.props.StringProperty(default="*.vmd", options={"HIDDEN"})

    scale: bpy.props.FloatProperty(
        name="Scale",
        description="Scaling factor for importing the motion",
        default=0.08,
    )
    margin: bpy.props.IntProperty(
        name="Margin",
        description="How many frames added before motion starting",
        min=0,
        default=5,
    )
    bone_mapper: bpy.props.EnumProperty(
        name="Bone Mapper",
        description="Select bone mapper",
        items=[
            ("BLENDER", "Blender", "Use blender bone name", 0),
            ("PMX", "PMX", "Use japanese name of MMD bone", 1),
            ("RENAMED_BONES", "Renamed bones", "Rename the bone of motion data to be blender suitable", 2),
        ],
        default="PMX",
    )
    rename_bones: bpy.props.BoolProperty(
        name="Rename Bones - L / R Suffix",
        description="Use Blender naming conventions for Left / Right paired bones",
        default=True,
    )
    use_underscore: bpy.props.BoolProperty(
        name="Rename Bones - Use Underscore",
        description="Will not use dot, e.g. if renaming bones, will use _R instead of .R",
        default=False,
    )
    dictionary: bpy.props.EnumProperty(
        name="Rename Bones To English",
        items=DictionaryEnum.get_dictionary_items,
        description="Translate bone names from Japanese to English using selected dictionary",
    )
    use_pose_mode: bpy.props.BoolProperty(
        name="Treat Current Pose as Rest Pose",
        description="You can pose the model to fit the original pose of a motion data, such as T-Pose or A-Pose",
        default=False,
        options={"SKIP_SAVE"},
    )
    use_mirror: bpy.props.BoolProperty(
        name="Mirror Motion",
        description="Import the motion by using X-Axis mirror",
        default=False,
    )
    update_scene_settings: bpy.props.BoolProperty(
        name="Update scene settings",
        description="Update frame range and frame rate (30 fps)",
        default=True,
    )
    use_NLA: bpy.props.BoolProperty(
        name="Use NLA",
        description="Import the motion as NLA strips",
        default=False,
    )
    files: bpy.props.CollectionProperty(
        type=OperatorFileListElement,
    )
    directory: bpy.props.StringProperty(subtype="DIR_PATH")

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) > 0

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "scale")
        layout.prop(self, "margin")
        layout.prop(self, "use_NLA")

        layout.prop(self, "bone_mapper")
        if self.bone_mapper == "RENAMED_BONES":
            layout.prop(self, "rename_bones")
            layout.prop(self, "use_underscore")
            layout.prop(self, "dictionary")
        layout.prop(self, "use_pose_mode")
        layout.prop(self, "use_mirror")

        layout.prop(self, "update_scene_settings")

    def execute(self, context):
        selected_objects = set(context.selected_objects)
        for i in frozenset(selected_objects):
            root = FnModel.find_root_object(i)
            if root == i:
                rig = Model(root)
                selected_objects.add(rig.armature())
                selected_objects.add(rig.morph_slider.placeholder())
                selected_objects |= set(rig.meshes())

        bone_mapper = None
        if self.bone_mapper == "PMX":
            bone_mapper = makePmxBoneMap
        elif self.bone_mapper == "RENAMED_BONES":
            bone_mapper = vmd_importer.RenamedBoneMapper(
                rename_LR_bones=self.rename_bones,
                use_underscore=self.use_underscore,
                translator=DictionaryEnum.get_translator(self.dictionary),
            ).init

        for file in self.files:
            start_time = time.time()
            importer = vmd_importer.VMDImporter(
                filepath=os.path.join(self.directory, file.name),
                scale=self.scale,
                bone_mapper=bone_mapper,
                use_pose_mode=self.use_pose_mode,
                frame_margin=self.margin,
                use_mirror=self.use_mirror,
                use_NLA=self.use_NLA,
            )

            for i in selected_objects:
                importer.assign(i)
            logging.info(" Finished importing motion in %f seconds.", time.time() - start_time)

        if self.update_scene_settings:
            auto_scene_setup.setupFrameRanges()
            auto_scene_setup.setupFps()
        context.scene.frame_set(context.scene.frame_current)
        return {"FINISHED"}


class ImportVpd(Operator, ImportHelper):
    bl_idname = "mmd_tools.import_vpd"
    bl_label = "Import VPD File (.vpd)"
    bl_description = "Import VPD file(s) to selected rig's Action Pose (.vpd)"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    files: bpy.props.CollectionProperty(type=OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: bpy.props.StringProperty(maxlen=1024, subtype="FILE_PATH", options={"HIDDEN", "SKIP_SAVE"})

    filename_ext = ".vpd"
    filter_glob: bpy.props.StringProperty(default="*.vpd", options={"HIDDEN"})

    scale: bpy.props.FloatProperty(
        name="Scale",
        description="Scaling factor for importing the pose",
        default=0.08,
    )
    bone_mapper: bpy.props.EnumProperty(
        name="Bone Mapper",
        description="Select bone mapper",
        items=[
            ("BLENDER", "Blender", "Use blender bone name", 0),
            ("PMX", "PMX", "Use japanese name of MMD bone", 1),
            ("RENAMED_BONES", "Renamed bones", "Rename the bone of pose data to be blender suitable", 2),
        ],
        default="PMX",
    )
    rename_bones: bpy.props.BoolProperty(
        name="Rename Bones - L / R Suffix",
        description="Use Blender naming conventions for Left / Right paired bones",
        default=True,
    )
    use_underscore: bpy.props.BoolProperty(
        name="Rename Bones - Use Underscore",
        description="Will not use dot, e.g. if renaming bones, will use _R instead of .R",
        default=False,
    )
    dictionary: bpy.props.EnumProperty(
        name="Rename Bones To English",
        items=DictionaryEnum.get_dictionary_items,
        description="Translate bone names from Japanese to English using selected dictionary",
    )
    use_pose_mode: bpy.props.BoolProperty(
        name="Treat Current Pose as Rest Pose",
        description="You can pose the model to fit the original pose of a pose data, such as T-Pose or A-Pose",
        default=False,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) > 0

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "scale")

        layout.prop(self, "bone_mapper")
        if self.bone_mapper == "RENAMED_BONES":
            layout.prop(self, "rename_bones")
            layout.prop(self, "use_underscore")
            layout.prop(self, "dictionary")
        layout.prop(self, "use_pose_mode")

    def execute(self, context):
        selected_objects = set(context.selected_objects)
        for i in frozenset(selected_objects):
            root = FnModel.find_root_object(i)
            if root == i:
                rig = Model(root)
                selected_objects.add(rig.armature())
                selected_objects.add(rig.morph_slider.placeholder())
                selected_objects |= set(rig.meshes())

        bone_mapper = None
        if self.bone_mapper == "PMX":
            bone_mapper = makePmxBoneMap
        elif self.bone_mapper == "RENAMED_BONES":
            bone_mapper = vmd_importer.RenamedBoneMapper(
                rename_LR_bones=self.rename_bones,
                use_underscore=self.use_underscore,
                translator=DictionaryEnum.get_translator(self.dictionary),
            ).init

        for f in self.files:
            importer = vpd_importer.VPDImporter(
                filepath=os.path.join(self.directory, f.name),
                scale=self.scale,
                bone_mapper=bone_mapper,
                use_pose_mode=self.use_pose_mode,
            )
            for i in selected_objects:
                importer.assign(i)
        return {"FINISHED"}


class ExportPmx(Operator, ExportHelper):
    bl_idname = "mmd_tools.export_pmx"
    bl_label = "Export PMX File (.pmx)"
    bl_description = "Export selected MMD model(s) to PMX file(s) (.pmx)"
    bl_options = {"PRESET"}

    filename_ext = ".pmx"
    filter_glob: bpy.props.StringProperty(default="*.pmx", options={"HIDDEN"})

    scale: bpy.props.FloatProperty(
        name="Scale",
        description="Scaling factor for exporting the model",
        default=12.5,
    )
    copy_textures: bpy.props.BoolProperty(
        name="Copy textures",
        description="Copy textures",
        default=True,
    )
    sort_materials: bpy.props.BoolProperty(
        name="Sort Materials",
        description=("Sort materials for alpha blending. " "WARNING: Will not work if you have " + "transparent meshes inside the model. " + "E.g. blush meshes"),
        default=False,
    )
    disable_specular: bpy.props.BoolProperty(
        name="Disable SPH/SPA",
        description="Disables all the Specular Map textures. It is required for some MME Shaders.",
        default=False,
    )
    visible_meshes_only: bpy.props.BoolProperty(
        name="Visible Meshes Only",
        description="Export visible meshes only",
        default=False,
    )
    overwrite_bone_morphs_from_action_pose: bpy.props.BoolProperty(
        name="Overwrite Bone Morphs",
        description="Overwrite the bone morphs from active Action Pose before exporting.",
        default=False,
    )
    translate_in_presets: bpy.props.BoolProperty(
        name="(Experimental) Translate in Presets",
        description="Translate in presets before exporting.",
        default=False,
    )
    sort_vertices: bpy.props.EnumProperty(
        name="Sort Vertices",
        description="Choose the method to sort vertices",
        items=[
            ("NONE", "None", "No sorting", 0),
            ("BLENDER", "Blender", "Use blender's internal vertex order", 1),
            ("CUSTOM", "Custom", 'Use custom vertex weight of vertex group "mmd_vertex_order"', 2),
        ],
        default="NONE",
    )
    log_level: bpy.props.EnumProperty(
        name="Log level",
        description="Select log level",
        items=LOG_LEVEL_ITEMS,
        default="DEBUG",
    )
    save_log: bpy.props.BoolProperty(
        name="Create a log file",
        description="Create a log file",
        default=False,
    )
    export_curves: bpy.props.BoolProperty(
        name="Export Curves",
        description="Convert curves to meshes before exporting",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj in context.selected_objects and FnModel.find_root_object(obj)

    def execute(self, context):
        try:
            folder = os.path.dirname(self.filepath)
            models = {FnModel.find_root_object(i) for i in context.selected_objects}
            for root in models:
                if root is None:
                    continue
                # use original self.filepath when export only one model
                # otherwise, use root object's name as file name
                if len(models) > 1:
                    model_name = bpy.path.clean_name(root.name)
                    model_folder = os.path.join(folder, model_name)
                    os.makedirs(model_folder, exist_ok=True)
                    self.filepath = os.path.join(model_folder, model_name + ".pmx")
                self._do_execute(context, root)
        except Exception as e:
            err_msg = traceback.format_exc()
            self.report({"ERROR"}, err_msg)
        return {"FINISHED"}

    def _do_execute(self, context, root):
        logger = logging.getLogger()
        logger.setLevel(self.log_level)
        if self.save_log:
            handler = log_handler(self.log_level, filepath=self.filepath + ".mmd_tools.export.log")
            logger.addHandler(handler)

        arm = FnModel.find_armature_object(root)
        if arm is None:
            self.report({"ERROR"}, '[Skipped] The armature object of MMD model "%s" can\'t be found' % root.name)
            return {"CANCELLED"}
        orig_pose_position = None
        if not root.mmd_root.is_built:  # use 'REST' pose when the model is not built
            orig_pose_position = arm.data.pose_position
            arm.data.pose_position = "REST"
            arm.update_tag()
            context.scene.frame_set(context.scene.frame_current)

        temp_meshes = []
        try:
            # Save export settings for quick export
            context.scene["mmd_tools_export_pmx_last_filepath"] = self.filepath
            context.scene["mmd_tools_export_pmx_last_scale"] = self.scale
            context.scene["mmd_tools_export_pmx_last_copy_textures"] = self.copy_textures
            context.scene["mmd_tools_export_pmx_last_sort_materials"] = self.sort_materials
            context.scene["mmd_tools_export_pmx_last_disable_specular"] = self.disable_specular
            context.scene["mmd_tools_export_pmx_last_visible_meshes_only"] = self.visible_meshes_only
            context.scene["mmd_tools_export_pmx_last_overwrite_bone_morphs"] = self.overwrite_bone_morphs_from_action_pose
            context.scene["mmd_tools_export_pmx_last_translate_in_presets"] = self.translate_in_presets
            context.scene["mmd_tools_export_pmx_last_sort_vertices"] = self.sort_vertices
            context.scene["mmd_tools_export_pmx_last_log_level"] = self.log_level
            context.scene["mmd_tools_export_pmx_last_save_log"] = self.save_log
            context.scene["mmd_tools_export_pmx_last_export_curves"] = self.export_curves
            
            # Get meshes and optionally convert curves
            meshes = list(FnModel.iterate_mesh_objects(root))
            
            if self.export_curves:
                from ..operators.export_cvt import convert_curves_to_meshes
                temp_meshes, _ = convert_curves_to_meshes(context, root)
                if temp_meshes:
                    meshes.extend(temp_meshes)
            
            if self.visible_meshes_only:
                meshes = [x for x in meshes if x in context.visible_objects]
            
            pmx_exporter.export(
                filepath=self.filepath,
                scale=self.scale,
                root=root,
                armature=FnModel.find_armature_object(root),
                meshes=meshes,
                rigid_bodies=FnModel.iterate_rigid_body_objects(root),
                joints=FnModel.iterate_joint_objects(root),
                copy_textures=self.copy_textures,
                overwrite_bone_morphs_from_action_pose=self.overwrite_bone_morphs_from_action_pose,
                translate_in_presets=self.translate_in_presets,
                sort_materials=self.sort_materials,
                sort_vertices=self.sort_vertices,
                disable_specular=self.disable_specular,
            )
            self.report({"INFO"}, 'Exported MMD model "%s" to "%s"' % (root.name, self.filepath))
        except:
            err_msg = traceback.format_exc()
            logging.error(err_msg)
            raise
        finally:
            # Clean up temporary meshes
            for mesh in temp_meshes:
                bpy.data.objects.remove(mesh)
                
            if orig_pose_position:
                arm.data.pose_position = orig_pose_position
            if self.save_log:
                logger.removeHandler(handler)

        return {"FINISHED"}


class ExportVmd(Operator, ExportHelper):
    bl_idname = "mmd_tools.export_vmd"
    bl_label = "Export VMD File (.vmd)"
    bl_description = "Export motion data of active object to a VMD file (.vmd)"
    bl_options = {"PRESET"}

    filename_ext = ".vmd"
    filter_glob: bpy.props.StringProperty(default="*.vmd", options={"HIDDEN"})

    scale: bpy.props.FloatProperty(
        name="Scale",
        description="Scaling factor for exporting the motion",
        default=12.5,
    )
    use_pose_mode: bpy.props.BoolProperty(
        name="Treat Current Pose as Rest Pose",
        description="You can pose the model to export a motion data to different pose base, such as T-Pose or A-Pose",
        default=False,
        options={"SKIP_SAVE"},
    )
    use_frame_range: bpy.props.BoolProperty(
        name="Use Frame Range",
        description="Export frames only in the frame range of context scene",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False

        if obj.mmd_type == "ROOT":
            return True
        if obj.mmd_type == "NONE" and (obj.type == "ARMATURE" or getattr(obj.data, "shape_keys", None)):
            return True
        if MMDCamera.isMMDCamera(obj) or MMDLamp.isMMDLamp(obj):
            return True

        return False

    def execute(self, context):
        params = {
            "filepath": self.filepath,
            "scale": self.scale,
            "use_pose_mode": self.use_pose_mode,
            "use_frame_range": self.use_frame_range,
        }

        obj = context.active_object
        if obj.mmd_type == "ROOT":
            rig = Model(obj)
            params["mesh"] = rig.morph_slider.placeholder(binded=True) or rig.firstMesh()
            params["armature"] = rig.armature()
            params["model_name"] = obj.mmd_root.name or obj.name
        elif getattr(obj.data, "shape_keys", None):
            params["mesh"] = obj
            params["model_name"] = obj.name
        elif obj.type == "ARMATURE":
            params["armature"] = obj
            params["model_name"] = obj.name
        else:
            for i in context.selected_objects:
                if MMDCamera.isMMDCamera(i):
                    params["camera"] = i
                elif MMDLamp.isMMDLamp(i):
                    params["lamp"] = i

        try:
            start_time = time.time()
            vmd_exporter.VMDExporter().export(**params)
            logging.info(" Finished exporting motion in %f seconds.", time.time() - start_time)
        except Exception as e:
            err_msg = traceback.format_exc()
            logging.error(err_msg)
            self.report({"ERROR"}, err_msg)

        return {"FINISHED"}


class ExportPmxQuick(Operator):
    bl_idname = "mmd_tools.export_pmx_quick"
    bl_label = "Quick Export PMX"
    bl_description = "Export selected MMD model using last export settings"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj in context.selected_objects and FnModel.find_root_object(obj)

    def execute(self, context):
        # Get export settings from addon preferences
        last_filepath = context.scene.get("mmd_tools_export_pmx_last_filepath", "")
        if not last_filepath:
            self.report({"ERROR"}, "No previous PMX export. Please use the regular export once first.")
            return {"CANCELLED"}
            
        try:
            root = FnModel.find_root_object(context.active_object)
            if root is None:
                self.report({"ERROR"}, "No MMD model found")
                return {"CANCELLED"}
                
            # Get last export settings from scene properties
            scene = context.scene
            scale = scene.get("mmd_tools_export_pmx_last_scale", 12.5)
            copy_textures = scene.get("mmd_tools_export_pmx_last_copy_textures", True)
            sort_materials = scene.get("mmd_tools_export_pmx_last_sort_materials", False)
            disable_specular = scene.get("mmd_tools_export_pmx_last_disable_specular", False)
            visible_meshes_only = scene.get("mmd_tools_export_pmx_last_visible_meshes_only", False)
            overwrite_bone_morphs_from_action_pose = scene.get("mmd_tools_export_pmx_last_overwrite_bone_morphs", False)
            translate_in_presets = scene.get("mmd_tools_export_pmx_last_translate_in_presets", False)
            sort_vertices = scene.get("mmd_tools_export_pmx_last_sort_vertices", "NONE")
            log_level = scene.get("mmd_tools_export_pmx_last_log_level", "DEBUG")
            save_log = scene.get("mmd_tools_export_pmx_last_save_log", False)
            export_curves = scene.get("mmd_tools_export_pmx_last_export_curves", True)
            
            # Setup logging
            logger = logging.getLogger()
            logger.setLevel(log_level)
            handler = None
            if save_log:
                handler = log_handler(log_level, filepath=last_filepath + ".mmd_tools.export.log")
                logger.addHandler(handler)
                
            arm = FnModel.find_armature_object(root)
            if arm is None:
                self.report({"ERROR"}, 'The armature object of MMD model "%s" can\'t be found' % root.name)
                return {"CANCELLED"}
                
            orig_pose_position = None
            if not root.mmd_root.is_built:  # use 'REST' pose when the model is not built
                orig_pose_position = arm.data.pose_position
                arm.data.pose_position = "REST"
                arm.update_tag()
                context.scene.frame_set(context.scene.frame_current)

            temp_meshes = []
            try:
                # Get meshes and optionally convert curves
                meshes = list(FnModel.iterate_mesh_objects(root))
                
                if export_curves:
                    from ..operators.export_cvt import convert_curves_to_meshes
                    temp_meshes, _ = convert_curves_to_meshes(context, root)
                    if temp_meshes:
                        meshes.extend(temp_meshes)
                
                if visible_meshes_only:
                    meshes = [x for x in meshes if x in context.visible_objects]
                
                pmx_exporter.export(
                    filepath=last_filepath,
                    scale=scale,
                    root=root,
                    armature=FnModel.find_armature_object(root),
                    meshes=meshes,
                    rigid_bodies=FnModel.iterate_rigid_body_objects(root),
                    joints=FnModel.iterate_joint_objects(root),
                    copy_textures=copy_textures,
                    overwrite_bone_morphs_from_action_pose=overwrite_bone_morphs_from_action_pose,
                    translate_in_presets=translate_in_presets,
                    sort_materials=sort_materials,
                    sort_vertices=sort_vertices,
                    disable_specular=disable_specular,
                )
                self.report({"INFO"}, 'Exported MMD model "%s" to "%s"' % (root.name, last_filepath))
            except:
                err_msg = traceback.format_exc()
                logging.error(err_msg)
                raise
            finally:
                # Clean up temporary meshes
                for mesh in temp_meshes:
                    bpy.data.objects.remove(mesh)
                    
                if orig_pose_position:
                    arm.data.pose_position = orig_pose_position
                if save_log and handler:
                    logger.removeHandler(handler)
                    
            return {"FINISHED"}
        except Exception as e:
            err_msg = traceback.format_exc()
            self.report({"ERROR"}, err_msg)
            return {"CANCELLED"}


class ExportVpd(Operator, ExportHelper):
    bl_idname = "mmd_tools.export_vpd"
    bl_label = "Export VPD File (.vpd)"
    bl_description = "Export to VPD file(s) (.vpd)"
    bl_description = "Export active rig's Action Pose to VPD file(s) (.vpd)"
    bl_options = {"PRESET"}

    filename_ext = ".vpd"
    filter_glob: bpy.props.StringProperty(default="*.vpd", options={"HIDDEN"})

    scale: bpy.props.FloatProperty(
        name="Scale",
        description="Scaling factor for exporting the pose",
        default=12.5,
    )
    pose_type: bpy.props.EnumProperty(
        name="Pose Type",
        description="Choose the pose type to export",
        items=[
            ("CURRENT", "Current Pose", "Current pose of the rig", 0),
            ("ACTIVE", "Active Pose", "Active pose of the rig's Action Pose", 1),
            ("ALL", "All Poses", "All poses of the rig's Action Pose (the pose name will be the file name)", 2),
        ],
        default="CURRENT",
    )
    use_pose_mode: bpy.props.BoolProperty(
        name="Treat Current Pose as Rest Pose",
        description="You can pose the model to export a pose data to different pose base, such as T-Pose or A-Pose",
        default=False,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False

        if obj.mmd_type == "ROOT":
            return True
        if obj.mmd_type == "NONE" and (obj.type == "ARMATURE" or getattr(obj.data, "shape_keys", None)):
            return True

        return False

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "scale")
        layout.prop(self, "pose_type", expand=True)
        if self.pose_type != "CURRENT":
            layout.prop(self, "use_pose_mode")

    def execute(self, context):
        params = {
            "filepath": self.filepath,
            "scale": self.scale,
            "pose_type": self.pose_type,
            "use_pose_mode": self.use_pose_mode,
        }

        obj = context.active_object
        if obj.mmd_type == "ROOT":
            rig = Model(obj)
            params["mesh"] = rig.morph_slider.placeholder(binded=True) or rig.firstMesh()
            params["armature"] = rig.armature()
            params["model_name"] = obj.mmd_root.name or obj.name
        elif getattr(obj.data, "shape_keys", None):
            params["mesh"] = obj
            params["model_name"] = obj.name
        elif obj.type == "ARMATURE":
            params["armature"] = obj
            params["model_name"] = obj.name

        try:
            vpd_exporter.VPDExporter().export(**params)
        except Exception as e:
            err_msg = traceback.format_exc()
            logging.error(err_msg)
            self.report({"ERROR"}, err_msg)
        return {"FINISHED"}
