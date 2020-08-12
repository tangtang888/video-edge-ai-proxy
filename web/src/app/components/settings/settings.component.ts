import { Component, OnInit } from '@angular/core';
import { EdgeService } from 'src/app/services/edge.service';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { Settings } from 'src/app/models/Settings';

@Component({
  selector: 'app-settings',
  templateUrl: './settings.component.html',
  styleUrls: ['./settings.component.scss']
})
export class SettingsComponent implements OnInit {

  settingsForm:FormGroup;
  showEdgeKey:Boolean = false;
  errorMessage:string = null;
  settings:Settings = {
    name: ""
  };
  submitted:Boolean = false;

  constructor(private edgeService:EdgeService, private _fb:FormBuilder) {
    this.settingsForm = this._fb.group({
      edge_key:[null, [Validators.minLength(3)]]
    })
  }

  ngOnInit(): void {
    this.edgeService.getSettings().subscribe(sett => {
      this.settings = sett;
    }, error => {
      this.errorMessage = error.message;
      console.error(error);
    })
  }



  onSubmit() {
    this.submitted = true;
    this.errorMessage = null;
    if (!this.settingsForm.valid) {
      return
    }
    this.settings.edge_key = this.settingsForm.get('edge_key').value;
    this.edgeService.overwriteSettings(this.settings).subscribe(ret => {
    }, error => {
      this.errorMessage = error.message;
      console.error(error);
    })
  }

  back() {
    history.back()
  }

}