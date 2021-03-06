// Copyright 2020 Wearless Tech Inc All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//    http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package api

import (
	"net/http"

	g "github.com/chryscloud/video-edge-ai-proxy/globals"
	"github.com/chryscloud/video-edge-ai-proxy/models"
	"github.com/chryscloud/video-edge-ai-proxy/services"
	"github.com/gin-gonic/gin"
	"github.com/gin-gonic/gin/binding"
)

type settingsHandler struct {
	settingsManager *services.SettingsManager
}

func NewSettingsHandler(settingsManager *services.SettingsManager) *settingsHandler {
	return &settingsHandler{
		settingsManager: settingsManager,
	}
}

// Get settings
func (sh *settingsHandler) Get(c *gin.Context) {
	s, err := sh.settingsManager.Get()
	if err != nil {
		g.Log.Error("failed to retrieve settings", err)
		AbortWithError(c, http.StatusInternalServerError, err.Error())
		return
	}
	c.JSON(http.StatusOK, s)
}

// Overwrite settings
func (sh *settingsHandler) Overwrite(c *gin.Context) {
	var settings models.Settings
	if err := c.ShouldBindWith(&settings, binding.JSON); err != nil {
		g.Log.Warn("missing required fields", err)
		AbortWithError(c, http.StatusBadRequest, err.Error())
		return
	}
	err := sh.settingsManager.Overwrite(&settings)
	if err != nil {
		AbortWithError(c, http.StatusInternalServerError, err.Error())
		return
	}
	c.Status(http.StatusAccepted)
}
