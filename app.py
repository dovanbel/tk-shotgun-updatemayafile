# Copyright (c) 2013 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
App that launches a Publish from inside of Shotgun.

"""

from tank.platform import Application
from tank import TankError
import tank
import sys
import os
import re
import shutil
import sgtk
import tempfile

class LaunchPublish(Application):
    
    def init_app(self):
        deny_permissions = self.get_setting("deny_permissions")
        deny_platforms = self.get_setting("deny_platforms")
        
        p = {
            "title": "Update the assets in this file",
            "entity_types" : ["PublishedFile"],
            "deny_permissions": deny_permissions,
            "deny_platforms": deny_platforms,
            "supports_multiple_selection": True
        }
        
        self.engine.register_command("update_publish", self.update_publish, p)


    def update_publish(self, entity_type, entity_ids):

        rootPath = os.path.dirname(self.tank.roots["primary"])

        regexp = "(.+\")(%s.+)(\".+)" % rootPath.replace(os.path.sep, "/")

        for uid in entity_ids:
            d = self.shotgun.find_one(entity_type, [["id", "is", uid]], ["name", "path", "published_file_type", "entity", "image", "task"])
            template_work = None
            
            if d.get("entity").get("type") == "Shot":
                template_work = self.get_template("template_shot_work")
            elif d.get("entity").get("type") == "Asset":
                template_work = self.get_template("template_asset_work")
            else:
                self.log_error("This file is not associated with a shot or an asset!") 
                return

            path_on_disk = d.get("path").get("local_path")
            published_file_type = d.get("published_file_type").get("name")


            tk = sgtk.sgtk_from_path(path_on_disk)
            ctx = tk.context_from_path(path_on_disk)
            sg_task = d.get("task")
            name = d.get("name")

            temp_file, thumbnail_path = tempfile.mkstemp(suffix=".png", prefix="tanktmp")
            if temp_file:
                os.close(temp_file) 

            sgtk.util.download_url( self.tank.shotgun, str(d.get("image")), thumbnail_path )

            # check that it exists        
            if not os.path.exists(path_on_disk):            
                self.log_error("The file associated with this publish, "
                                "%s, cannot be found on disk!" % path_on_disk)
                continue

            if published_file_type != "Maya Scene":
                self.log_error("The type file associated with this publish, "
                                "%s, cannot be updated!" % published_file_type)
                continue

            base, ext = os.path.splitext(os.path.basename(path_on_disk))

            if ext != ".ma":
                self.log_error("Only ma files can be updated!")
                continue



            fo = open(path_on_disk, "r")

            fileTemplate = self.tank.template_from_path(path_on_disk) 
            if not fileTemplate:
                self.log_error("The type file associated with this publish has no template")  
                continue

            fields = fileTemplate.get_fields(path_on_disk)               
            if not "version" in fields:
                self.log_error("The type file associated with this publish has no version number") 
                continue


            #workFolderTpl = fileTemplate.parent

            workfile = template_work.apply_fields(fields)
            # check the latest version of workfile....
            all_versions = self.tank.paths_from_template(template_work, 
                                          fields, 
                                          skip_keys=["version", "SEQ", "eye"])             
            latest_version = 0
            for ver in all_versions:
                fd = template_work.get_fields(ver)
                if fd["version"] > latest_version:
                    latest_version = fd["version"]

            # incrementing version number for publish
            fields["version"] = latest_version
            version_number = latest_version
            dest_path = fileTemplate.apply_fields(fields) 
            dest_path = dest_path.replace(os.path.sep, "/")

            if os.path.exists(dest_path):
                self.log_error("Publish file %s already exists!" % dest_path) 
                continue


            fields["version"] = latest_version + 1
            workfile = template_work.apply_fields(fields)


            destfile = open( dest_path ,"w")

            lines = fo.readlines()
            #self.engine.log_info(lines)
            fo.close()

            fieldsforSearch = ["entity", 
                      "entity.Asset.sg_asset_type", # grab asset type if it is an asset
                      "code",
                      "name", 
                      "version_number",
                      ]

            for line in lines:
                canWrite = True
                m = re.search(regexp, line)
                if m:
                    filePath = m.group(2)

                    sg_data = tank.util.find_publish(self.tank, [filePath], fields=fieldsforSearch)
                    for (path, sg_chunk) in sg_data.items(): 

                        #file_name = sg_chunk.get("path").replace("/", os.path.sep) 
                        matching_template = self.tank.template_from_path(path) 

                        if matching_template: 
                            fields = matching_template.get_fields(path) 
                            if "version" not in fields: 
                                continue

                            all_versions = self.tank.paths_from_template(matching_template, 
                                                          fields, 
                                                          skip_keys=["version", "SEQ", "eye"]) 

                            # now look for the highest version number...
                            latest_version = 0
                            for ver in all_versions:
                                fd = matching_template.get_fields(ver)
                                if fd["version"] > latest_version:
                                    latest_version = fd["version"]

                            current_version = fields["version"]
                            
                            if (latest_version != current_version):
                                fields["version"] = latest_version
                                new_path = matching_template.apply_fields(fields) 
                                new_path = new_path.replace(os.path.sep, "/")
                                self.engine.log_info("%s not up to date, latest is %i" %(path, latest_version))

                                newLine = "%s%s%s\n" % (m.group(1), new_path, m.group(3))

                                destfile.write(newLine)
                                canWrite = False
                
                if canWrite:
                    destfile.write(line)
                   
            destfile.close()

            # publishing the file
            args = {
                "tk": tk,
                "context": ctx,
                "comment": "Automated Asset Update",
                "path": dest_path.replace("/", os.path.sep),
                "name": name,
                "task": sg_task,
                "thumbnail_path": thumbnail_path,
                "version_number": version_number,
                "published_file_type": published_file_type,
            }

            sgtk.util.register_publish(**args)            


            shutil.copyfile(dest_path, workfile)

            if thumbnail_path:
                os.remove(thumbnail_path)

        self.engine.log_info("done")

