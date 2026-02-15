#include <AFMotor.h>

AF_DCMotor FL(1);
AF_DCMotor FR(4);
AF_DCMotor RL(2);
AF_DCMotor RR(3);

int speedVal = 180;

void stopAll() {
  FL.run(RELEASE);
  FR.run(RELEASE);
  RL.run(RELEASE);
  RR.run(RELEASE);
}

void setAllSpeed(int spd){
  FL.setSpeed(spd);
  FR.setSpeed(spd);
  RL.setSpeed(spd);
  RR.setSpeed(spd);
}

void forward(){
  setAllSpeed(speedVal);
  FL.run(FORWARD);
  FR.run(BACKWARD);
  RL.run(BACKWARD);
  RR.run(FORWARD);
}

void backward(){
  setAllSpeed(speedVal);
  FL.run(BACKWARD);
  FR.run(FORWARD);
  RL.run(FORWARD);
  RR.run(BACKWARD);
}

void strafeLeft(){
  setAllSpeed(speedVal);
  FL.run(FORWARD);
  FR.run(FORWARD);
  RL.run(FORWARD);
  RR.run(FORWARD);
}

void strafeRight(){
  setAllSpeed(speedVal);
  FL.run(BACKWARD);
  FR.run(BACKWARD);
  RL.run(BACKWARD);
  RR.run(BACKWARD);
}

void rotateLeft(){
  setAllSpeed(speedVal);
  FL.run(BACKWARD);
  FR.run(BACKWARD);
  RL.run(FORWARD);
  RR.run(FORWARD);
}

void rotateRight(){
  setAllSpeed(speedVal);
  FL.run(FORWARD);
  FR.run(FORWARD);
  RL.run(BACKWARD);
  RR.run(BACKWARD);
}

void leftFront(){
  setAllSpeed(speedVal);
  FL.run(RELEASE);
  FR.run(BACKWARD);
  RL.run(BACKWARD);
  RR.run(RELEASE);
}

void rightFront(){
  setAllSpeed(speedVal);
  FL.run(FORWARD);
  FR.run(RELEASE);
  RL.run(RELEASE);
  RR.run(FORWARD);
}

void leftRear(){
  setAllSpeed(speedVal);
  FL.run(BACKWARD);
  FR.run(RELEASE);
  RL.run(RELEASE);
  RR.run(BACKWARD);
}

void rightRear(){
  setAllSpeed(speedVal);
  FL.run(RELEASE);
  FR.run(FORWARD);
  RL.run(FORWARD);
  RR.run(RELEASE);
}

void frontAxleLeftTurn(){
  setAllSpeed(speedVal);
  FL.run(RELEASE);
  FR.run(RELEASE);
  RL.run(BACKWARD);
  RR.run(FORWARD);
}

void frontAxleRightTurn(){
  setAllSpeed(speedVal);
  FL.run(RELEASE);
  FR.run(RELEASE);
  RL.run(FORWARD);
  RR.run(BACKWARD);
}

void rearAxleleftTurn(){
  setAllSpeed(speedVal);
  FL.run(BACKWARD);
  FR.run(BACKWARD);
  RL.run(RELEASE);
  RR.run(RELEASE);
}

void rearAxleRightTurn(){
  setAllSpeed(speedVal);
  FL.run(FORWARD);
  FR.run(FORWARD);
  RL.run(RELEASE);
  RR.run(RELEASE);
}

void setup() {
  Serial.begin(9600);
  stopAll();
}

void loop() {
  if (Serial.available()) {
    char cmd = Serial.read();

    if(cmd=='F') forward();
    else if(cmd=='B') backward();
    else if(cmd=='L') strafeLeft();
    else if(cmd=='R') strafeRight();
    else if(cmd=='Q') rotateLeft();
    else if(cmd=='E') rotateRight();
    else if(cmd=='S') stopAll();
    else if(cmd=='LF') leftFront();
    else if(cmd=='RF') rightFront();
    else if(cmd=='LR') leftRear();
    else if(cmd=='RR') rightRear();
    else if(cmd=='FALT') frontAxleLeftTurn();
    else if(cmd=='FART') frontAxleRightTurn();
    else if(cmd=='RALT') rearAxleleftTurn();
    else if(cmd=='RART') rearAxleRightTurn();
  }
}
