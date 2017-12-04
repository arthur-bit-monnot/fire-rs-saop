//***************************************************************************
// Copyright 2017 OceanScan - Marine Systems & Technology, Lda.             *
//***************************************************************************
// Licensed under the Apache License, Version 2.0 (the "License");          *
// you may not use this file except in compliance with the License.         *
// You may obtain a copy of the License at                                  *
//                                                                          *
// http://www.apache.org/licenses/LICENSE-2.0                               *
//                                                                          *
// Unless required by applicable law or agreed to in writing, software      *
// distributed under the License is distributed on an "AS IS" BASIS,        *
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. *
// See the License for the specific language governing permissions and      *
// limitations under the License.                                           *
//***************************************************************************
// Author: Ricardo Martins                                                  *
//***************************************************************************
// Automatically generated.                                                 *
//***************************************************************************
// IMC XML MD5: 4d8734a1111656aac56f803acdc90c22                            *
//***************************************************************************

#ifndef IMC_LEAKSIMULATION_HPP_INCLUDED_
#define IMC_LEAKSIMULATION_HPP_INCLUDED_

// ISO C++ 98 headers.
#include <ostream>
#include <string>
#include <vector>

// IMC headers.
#include "../Base/Config.hpp"
#include "../Base/Message.hpp"
#include "../Base/InlineMessage.hpp"
#include "../Base/MessageList.hpp"
#include "../Base/JSON.hpp"
#include "../Base/Serialization.hpp"
#include "../Spec/Enumerations.hpp"
#include "../Spec/Bitfields.hpp"

namespace IMC
{
  //! Leak Simulation.
  class LeakSimulation: public Message
  {
  public:
    //! Operation.
    enum OperationEnum
    {
      //! Leaks Off.
      LSIM_OFF = 0,
      //! Leaks On.
      LSIM_ON = 1
    };

    //! Operation.
    uint8_t op;
    //! Leak Entities.
    std::string entities;

    static uint16_t
    getIdStatic(void)
    {
      return 51;
    }

    static LeakSimulation*
    cast(Message* msg__)
    {
      return (LeakSimulation*)msg__;
    }

    LeakSimulation(void)
    {
      m_header.mgid = LeakSimulation::getIdStatic();
      clear();
    }

    LeakSimulation*
    clone(void) const
    {
      return new LeakSimulation(*this);
    }

    void
    clear(void)
    {
      op = 0;
      entities.clear();
    }

    bool
    fieldsEqual(const Message& msg__) const
    {
      const IMC::LeakSimulation& other__ = static_cast<const LeakSimulation&>(msg__);
      if (op != other__.op) return false;
      if (entities != other__.entities) return false;
      return true;
    }

    uint8_t*
    serializeFields(uint8_t* bfr__) const
    {
      uint8_t* ptr__ = bfr__;
      ptr__ += IMC::serialize(op, ptr__);
      ptr__ += IMC::serialize(entities, ptr__);
      return ptr__;
    }

    size_t
    deserializeFields(const uint8_t* bfr__, size_t size__)
    {
      const uint8_t* start__ = bfr__;
      bfr__ += IMC::deserialize(op, bfr__, size__);
      bfr__ += IMC::deserialize(entities, bfr__, size__);
      return bfr__ - start__;
    }

    size_t
    reverseDeserializeFields(const uint8_t* bfr__, size_t size__)
    {
      const uint8_t* start__ = bfr__;
      bfr__ += IMC::deserialize(op, bfr__, size__);
      bfr__ += IMC::reverseDeserialize(entities, bfr__, size__);
      return bfr__ - start__;
    }

    uint16_t
    getId(void) const
    {
      return LeakSimulation::getIdStatic();
    }

    const char*
    getName(void) const
    {
      return "LeakSimulation";
    }

    size_t
    getFixedSerializationSize(void) const
    {
      return 1;
    }

    size_t
    getVariableSerializationSize(void) const
    {
      return IMC::getSerializationSize(entities);
    }

    void
    fieldsToJSON(std::ostream& os__, unsigned nindent__) const
    {
      IMC::toJSON(os__, "op", op, nindent__);
      IMC::toJSON(os__, "entities", entities, nindent__);
    }
  };
}

#endif
